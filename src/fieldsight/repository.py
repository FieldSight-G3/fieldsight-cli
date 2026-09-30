from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from pgvector.sqlalchemy import (
    VECTOR as _VECTOR,  # noqa: F401 - registers vector type for reflection
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import MetaData, Table, create_engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from fieldsight.config import settings
from fieldsight.harness.bounds import BoundsConfig
from fieldsight.harness.escalation.review import (
    CitationReference,
    PendingReview,
    ReviewDecision,
    ReviewWriteFailed,
)
from fieldsight.security.redaction import redact_payload, redact_text

RecordType = TypeVar("RecordType", bound=BaseModel)

class _Repository:
    def __init__(self, table_name: str, dsn: str | None = None) -> None:
        url = dsn or settings.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(url, pool_pre_ping=True)
        self.table = Table(table_name, MetaData(), autoload_with=self.engine)

    def _get(self, key: str, value: UUID | str, model: type[RecordType]) -> RecordType | None:
        columns = [self.table.c[name] for name in model.model_fields]
        statement = select(*columns).where(self.table.c[key] == value)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return model.model_validate(dict(row)) if row is not None else None

class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: UUID
    establishment: str
    submitted_at: datetime
    normalized_fields: dict[str, Any]
    narrative: str | None
    outcome: dict[str, Any] | None
    deciding_rule: str | None
    status: str
    photo_verdicts: dict[str, Any] | None

class IncidentRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)

    def create(self, establishment: str, normalized_fields: dict[str, Any], narrative: str | None = None, owner_analyst_id: UUID | None = None, photo_verdicts: dict[str, Any] | None = None) -> UUID:
        statement = insert(self.table).values(
            establishment=establishment,
            normalized_fields=normalized_fields,
            narrative=narrative,
            owner_analyst_id=owner_analyst_id,
            photo_verdicts=photo_verdicts
        ).returning(self.table.c.incident_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, incident_id: UUID) -> IncidentRecord | None:
        return self._get("incident_id", incident_id, IncidentRecord)

    def save_analysis(self, incident_id: UUID, correlation_id: UUID, outcome: dict[str, Any] | None, deciding_rule: str | None, rule_invocations: list[dict[str, Any]], escalation_triggers: dict[str, Any] | None, *, requires_review: bool, command: str = "analyze", workers_dispatched: dict[str, Any] | None = None,
                      tool_invocations: dict[str, Any] | None = None, model_calls: dict[str, Any] | None = None,
                      reviewer_verdicts: dict[str, Any] | None = None, dossier: dict[str, Any] | None = None) -> UUID:
        """One turn's writes in one transaction; outcome is None for a turn that must not overwrite it, like ask."""
        metadata = MetaData()
        run_records = Table("run_records", metadata, autoload_with=self.engine)
        review_queue = Table("review_queue", metadata, autoload_with=self.engine) if requires_review else None
        with self.engine.begin() as connection:
            if outcome is not None:
                updated = connection.execute(
                    update(self.table)
                    .where(self.table.c.incident_id == incident_id)
                    .values(outcome=outcome, deciding_rule=deciding_rule)
                    .returning(self.table.c.incident_id)
                ).scalar_one_or_none()
                if updated is None:
                    raise LookupError(f"Incident {incident_id} does not exist")
            run_id = connection.execute(
                insert(run_records)
                .values(
                    correlation_id=correlation_id,
                    incident_id=incident_id,
                    command=command,
                    workers_dispatched=workers_dispatched,
                    rule_invocations={"items": rule_invocations},
                    escalation_triggers=escalation_triggers,
                    tool_invocations=tool_invocations,
                    model_calls=model_calls,
                    reviewer_verdicts=reviewer_verdicts,
                    dossier=dossier,
                )
                .returning(run_records.c.run_id)
            ).scalar_one()
            if review_queue is not None:
                connection.execute(
                    insert(review_queue).values(
                        incident_id=incident_id,
                        triggers=escalation_triggers,
                    )
                )
        return run_id

    def save_analysis_for_review(self, incident_id: UUID, correlation_id: UUID, outcome: dict[str, Any] | None, deciding_rule: str | None, rule_invocations: list[dict[str, Any]], escalation_triggers: dict[str, Any], *, submitting_analyst_id: UUID, dossier_snapshot: dict[str, Any], citations: dict[str, CitationReference], command: str = "analyze", workers_dispatched: dict[str, Any] | None = None, tool_invocations: dict[str, Any] | None = None, model_calls: dict[str, Any] | None = None, reviewer_verdicts: dict[str, Any] | None = None, dossier: dict[str, Any] | None = None) -> UUID:
        """Like save_analysis with requires_review, but queues an immutable dossier snapshot for get_pending; outcome is None for a turn that must not overwrite it, like ask."""
        metadata = MetaData()
        run_records = Table("run_records", metadata, autoload_with=self.engine)
        review_queue = Table("review_queue", metadata, autoload_with=self.engine)
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(self.table.c.incident_id).where(self.table.c.incident_id == incident_id)
            ).scalar_one_or_none()
            if exists is None:
                raise LookupError(f"Incident {incident_id} does not exist")
            if outcome is not None:
                connection.execute(
                    update(self.table)
                    .where(self.table.c.incident_id == incident_id)
                    .values(outcome=outcome, deciding_rule=deciding_rule)
                )
            run_id = connection.execute(
                insert(run_records)
                .values(
                    correlation_id=correlation_id,
                    incident_id=incident_id,
                    command=command,
                    workers_dispatched=workers_dispatched,
                    rule_invocations={"items": rule_invocations},
                    escalation_triggers=escalation_triggers,
                    tool_invocations=tool_invocations,
                    model_calls=model_calls,
                    reviewer_verdicts=reviewer_verdicts,
                    dossier=dossier,
                )
                .returning(run_records.c.run_id)
            ).scalar_one()
            connection.execute(
                insert(review_queue).values(
                    incident_id=incident_id,
                    triggers=escalation_triggers,
                    submitting_analyst_id=submitting_analyst_id,
                    dossier_snapshot=dossier_snapshot,
                    citations={key: value.model_dump(mode="json") for key, value in citations.items()}
                )
            )
        return run_id

class RunRecordRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    correlation_id: UUID
    incident_id: UUID | None
    command: str
    workers_dispatched: dict[str, Any] | None
    tool_invocations: dict[str, Any] | None
    rule_invocations: dict[str, Any] | None
    escalation_triggers: dict[str, Any] | None
    model_calls: dict[str, Any] | None
    reviewer_verdicts: dict[str, Any] | None
    created_at: datetime

class RunRecordRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("run_records", dsn)

    def create(
        self,
        correlation_id: UUID,
        command: str,
        incident_id: UUID | None = None,
        workers_dispatched: dict[str, Any] | None = None,
        tool_invocations: dict[str, Any] | None = None,
        rule_invocations: dict[str, Any] | None = None,
        escalation_triggers: dict[str, Any] | None = None,
        model_calls: dict[str, Any] | None = None
    ) -> UUID:
        statement = insert(self.table).values(
            correlation_id=correlation_id,
            command=command,
            incident_id=incident_id,
            workers_dispatched=workers_dispatched,
            tool_invocations=tool_invocations,
            rule_invocations=rule_invocations,
            escalation_triggers=escalation_triggers,
            model_calls=model_calls
        ).returning(self.table.c.run_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, run_id: UUID) -> RunRecordRecord | None:
        return self._get("run_id", run_id, RunRecordRecord)

    def latest(self, incident_id: UUID, commands: tuple[str, ...] = ("analyze", "ask")) -> dict[str, Any] | None:
        """The incident's most recent run record of those commands, with every column the table has, or None."""
        statement = (
            select(self.table)
            .where(self.table.c.incident_id == incident_id, self.table.c.command.in_(commands))
            .order_by(self.table.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def record_correction(
        self,
        original_run_id: UUID,
        reason: str,
        correlation_id: UUID,
        *,
        workers_dispatched: dict[str, Any] | None = None,
        tool_invocations: dict[str, Any] | None = None,
        rule_invocations: dict[str, Any] | None = None,
        escalation_triggers: dict[str, Any] | None = None,
        model_calls: dict[str, Any] | None = None
    ) -> UUID:
        """A new, PII-redacted record that references the run it corrects; the original row is never edited."""
        if not reason.strip():
            raise ValueError("A correction needs a reason")
        with self.engine.begin() as connection:
            original = connection.execute(
                select(self.table.c.incident_id).where(self.table.c.run_id == original_run_id)
            ).one_or_none()
            if original is None:
                raise LookupError(f"Run {original_run_id} does not exist")
            return connection.execute(
                insert(self.table).values(
                    correlation_id=correlation_id,
                    command="correction",
                    incident_id=original.incident_id,
                    corrects_run_id=original_run_id,
                    correction_reason=redact_text(reason, "correction_reason"),
                    workers_dispatched=redact_payload(workers_dispatched),
                    tool_invocations=redact_payload(tool_invocations),
                    rule_invocations=redact_payload(rule_invocations),
                    escalation_triggers=redact_payload(escalation_triggers),
                    model_calls=redact_payload(model_calls)
                ).returning(self.table.c.run_id)
            ).scalar_one()

    def corrections_of(self, run_id: UUID) -> list[dict[str, Any]]:
        """Every correction recorded against a run, oldest first."""
        statement = (
            select(self.table.c.run_id, self.table.c.correction_reason, self.table.c.created_at)
            .where(self.table.c.corrects_run_id == run_id)
            .order_by(self.table.c.created_at, self.table.c.run_id)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]

class ReviewQueueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_id: UUID
    incident_id: UUID
    triggers: dict[str, Any]
    status: str
    decision: dict[str, Any] | None
    created_at: datetime

class ReviewQueueRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("review_queue", dsn)

    def create(self, incident_id: UUID, triggers: dict[str, Any]) -> UUID:
        statement = insert(self.table).values(
            incident_id=incident_id,
            triggers=triggers
        ).returning(self.table.c.queue_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, queue_id: UUID) -> ReviewQueueRecord | None:
        return self._get("queue_id", queue_id, ReviewQueueRecord)

    def list_pending(self, reviewer_id: UUID | None = None) -> list[ReviewQueueRecord]:
        """Every pending item, oldest first; with a reviewer, only those over an establishment they hold a grant for."""
        columns = [self.table.c[name] for name in ReviewQueueRecord.model_fields]
        statement = select(*columns).where(self.table.c.status == "pending").order_by(self.table.c.created_at)
        if reviewer_id is not None:
            metadata = MetaData()
            incidents = Table("incidents", metadata, autoload_with=self.engine)
            grants = Table("grants", metadata, autoload_with=self.engine)
            statement = (
                statement.join(incidents, incidents.c.incident_id == self.table.c.incident_id)
                .join(grants, grants.c.establishment == incidents.c.establishment)
                .where(grants.c.analyst_id == reviewer_id)
            )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [ReviewQueueRecord.model_validate(dict(row)) for row in rows]

    def pending_queue_id(self, incident_id: UUID) -> UUID | None:
        """The queue id of the incident's oldest pending review, or None when it has none."""
        statement = (
            select(self.table.c.queue_id)
            .where(self.table.c.incident_id == incident_id, self.table.c.status == "pending")
            .order_by(self.table.c.created_at)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none()

    def pending_for_incident(self, incident_id: UUID) -> PendingReview | None:
        """The incident's oldest pending review with its snapshot, or None when it has none."""
        queue_id = self.pending_queue_id(incident_id)
        return self.get_pending(queue_id) if queue_id is not None else None

    def get_pending(self, queue_id: UUID) -> PendingReview | None:
        columns = [self.table.c[name] for name in ("queue_id", "incident_id", "submitting_analyst_id", "dossier_snapshot", "citations")]
        statement = select(*columns).where(self.table.c.queue_id == queue_id, self.table.c.status == "pending")
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None or row["submitting_analyst_id"] is None or row["dossier_snapshot"] is None or row["citations"] is None:
            return None
        citations = {key: CitationReference.model_validate(value) for key, value in row["citations"].items()}
        return PendingReview(queue_id=row["queue_id"], incident_id=row["incident_id"], submitting_analyst_id=row["submitting_analyst_id"], original_payload=row["dossier_snapshot"], original_citations=citations)

    def reviewer_entitled(self, reviewer_id: UUID, incident_id: UUID) -> bool:
        metadata = MetaData()
        incidents = Table("incidents", metadata, autoload_with=self.engine)
        grants = Table("grants", metadata, autoload_with=self.engine)
        statement = (
            select(grants.c.grant_id)
            .join(incidents, incidents.c.establishment == grants.c.establishment)
            .where(incidents.c.incident_id == incident_id, grants.c.analyst_id == reviewer_id)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def record_if_pending(self, decision: ReviewDecision, *, limits: BoundsConfig | None = None) -> bool:
        limits = limits or BoundsConfig.from_environment()
        payload = decision.model_dump(mode="json")
        statement = (
            update(self.table)
            .where(self.table.c.queue_id == decision.queue_id, self.table.c.incident_id == decision.incident_id, self.table.c.status == "pending")
            .values(status=decision.status, decision=payload, reviewer_id=decision.reviewer_id, decided_at=decision.decided_at)
            .returning(self.table.c.queue_id)
        )
        recorded = select(self.table.c.decision).where(self.table.c.queue_id == decision.queue_id)
        for attempt in range(limits.db_write_max_attempts):
            try:
                with self.engine.begin() as connection:
                    # a dropped connection can hide a commit; the same decision already stored is a success, not a conflict
                    if attempt and connection.execute(recorded).scalar_one_or_none() == payload:
                        return True
                    return connection.execute(statement).scalar_one_or_none() is not None
            except OperationalError as error:
                if attempt + 1 == limits.db_write_max_attempts:
                    raise ReviewWriteFailed(f"Review decision not saved after {limits.db_write_max_attempts} attempts") from error
                time.sleep(limits.db_write_backoff_seconds * 2 ** attempt * (1 + random.random()))
        raise AssertionError("unreachable")

class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    analyst_id: UUID
    incident_id: UUID
    participant: str
    created_at: datetime

class SessionRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("sessions", dsn)

    def create(self, thread_id: str, analyst_id: UUID, incident_id: UUID, participant: str) -> str:
        statement = insert(self.table).values(
            thread_id=thread_id,
            analyst_id=analyst_id,
            incident_id=incident_id,
            participant=participant
        ).returning(self.table.c.thread_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, thread_id: str) -> SessionRecord | None:
        return self._get("thread_id", thread_id, SessionRecord)

    def get_or_create(self, thread_id: str, analyst_id: UUID, incident_id: UUID, participant: str) -> SessionRecord:
        """ one row per thread, created on first use and reused after; a thread already bound elsewhere is refused """

        statement = pg_insert(self.table).values(
            thread_id=thread_id,
            analyst_id=analyst_id,
            incident_id=incident_id,
            participant=participant,
        ).on_conflict_do_nothing(index_elements=["thread_id"])
        with self.engine.begin() as connection:
            connection.execute(statement)

        record = self.get(thread_id)
        if record is None or (record.analyst_id, record.incident_id, record.participant) != (analyst_id, incident_id, participant):
            raise ValueError(f"thread {thread_id!r} is already bound to a different session")
        return record

class AnalystRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("analysts", dsn)

    def email_for_iam_principal(self, role_arn: str) -> str | None:
        statement = select(self.table.c.email).where(self.table.c.iam_role_arn == role_arn)
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none()

    def analyst_id_for_iam_principal(self, role_arn: str) -> UUID | None:
        statement = select(self.table.c.analyst_id).where(self.table.c.iam_role_arn == role_arn)
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none()

    def latest_establishment(self, analyst_id: UUID) -> str | None:
        """The establishment of the analyst's most recent grant, or None when they hold no grant."""
        grants = Table("grants", MetaData(), autoload_with=self.engine)
        statement = (
            select(grants.c.establishment)
            .where(grants.c.analyst_id == analyst_id)
            .order_by(grants.c.created_at.desc(), grants.c.establishment)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none()

    def assign_iam_role(self, analyst_id: UUID, role_arn: str) -> bool:
        statement = (
            update(self.table)
            .where(self.table.c.analyst_id == analyst_id)
            .values(iam_role_arn=role_arn)
            .returning(self.table.c.analyst_id)
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

class GatewayReadRepository(_Repository):
    """Queries behind the two Gateway read tools; the entitlement policy stays in tool_store."""

    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)
        metadata = MetaData()
        self.sessions = Table("sessions", metadata, autoload_with=self.engine)
        self.analysts = Table("analysts", metadata, autoload_with=self.engine)
        self.grants = Table("grants", metadata, autoload_with=self.engine)

    def bound_session(self, email: str, thread_id: str) -> dict[str, Any] | None:
        statement = (
            select(self.sessions.c.analyst_id, self.sessions.c.incident_id)
            .join(self.analysts, self.analysts.c.analyst_id == self.sessions.c.analyst_id)
            .where(self.sessions.c.thread_id == thread_id, self.analysts.c.email == email)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def tool_incident(self, incident_id: UUID) -> dict[str, Any] | None:
        statement = (
            select(self.table.c.incident_id, self.table.c.establishment, self.table.c.normalized_fields,
                   self.table.c.embedding, self.table.c.narrative)
            .where(self.table.c.incident_id == incident_id)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def has_grant(self, analyst_id: UUID, establishment: str) -> bool:
        statement = (
            select(self.grants.c.grant_id)
            .where(self.grants.c.analyst_id == analyst_id, self.grants.c.establishment == establishment)
            .limit(1)
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def similar_incidents(self, incident_id: UUID, embedding: Any, analyst_id: UUID, limit: int) -> list[dict[str, Any]]:
        """Closed incidents nearest the embedding, only from establishments the analyst is granted."""
        distance = self.table.c.embedding.cosine_distance(embedding)
        statement = (
            select(self.table.c.incident_id, self.table.c.outcome, self.table.c.deciding_rule,
                   self.table.c.narrative, distance.label("distance"))
            .join(self.grants, (self.grants.c.establishment == self.table.c.establishment) & (self.grants.c.analyst_id == analyst_id))
            .where(self.table.c.incident_id != incident_id, self.table.c.embedding.is_not(None),
                   self.table.c.outcome.is_not(None), self.table.c.deciding_rule.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]


class SeedRepository(_Repository):
    """Idempotent inserts for the demo analysts, grants and historical incidents; a second run adds nothing."""

    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)
        metadata = MetaData()
        self.analysts = Table("analysts", metadata, autoload_with=self.engine)
        self.grants = Table("grants", metadata, autoload_with=self.engine)

    def seed(self, analysts: list[dict[str, Any]], grants: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> dict[str, int]:
        added = {"analysts": 0, "grants": 0, "incidents": 0}
        with self.engine.begin() as connection:
            for analyst in analysts:
                statement = pg_insert(self.analysts).values(**analyst).on_conflict_do_nothing(
                    index_elements=[self.analysts.c.analyst_id]
                ).returning(self.analysts.c.analyst_id)
                added["analysts"] += int(connection.execute(statement).scalar_one_or_none() is not None)
            for grant in grants:
                statement = pg_insert(self.grants).values(**grant).on_conflict_do_nothing(
                    index_elements=[self.grants.c.analyst_id, self.grants.c.establishment]
                ).returning(self.grants.c.grant_id)
                added["grants"] += int(connection.execute(statement).scalar_one_or_none() is not None)
            for incident in incidents:
                statement = pg_insert(self.table).values(**incident).on_conflict_do_nothing(
                    index_elements=[self.table.c.incident_id]
                ).returning(self.table.c.incident_id)
                added["incidents"] += int(connection.execute(statement).scalar_one_or_none() is not None)
        return added


def database_ready(engine: Any) -> bool:
    """The readiness probe: one round trip to Postgres. Connection failures mean not ready; anything else is a bug and raises."""
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError:
        return False
    return True
