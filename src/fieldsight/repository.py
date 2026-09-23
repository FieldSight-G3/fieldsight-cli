from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from pgvector.sqlalchemy import VECTOR as _VECTOR
from pydantic import BaseModel, ConfigDict
from sqlalchemy import MetaData, Table, create_engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fieldsight.config import settings

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

class IncidentRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)

    def create(self, establishment: str, normalized_fields: dict[str, Any], narrative: str | None = None) -> UUID:
        statement = insert(self.table).values(
            establishment=establishment,
            normalized_fields=normalized_fields,
            narrative=narrative
        ).returning(self.table.c.incident_id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one()

    def get(self, incident_id: UUID) -> IncidentRecord | None:
        return self._get("incident_id", incident_id, IncidentRecord)

    def save_analysis(
        self,
        incident_id: UUID,
        correlation_id: UUID,
        outcome: dict[str, Any],
        deciding_rule: str,
        rule_invocations: list[dict[str, Any]],
        escalation_triggers: dict[str, Any]
    ) -> UUID:
        metadata = MetaData()
        run_records = Table("run_records", metadata, autoload_with=self.engine)
        review_queue = (
            Table("review_queue", metadata, autoload_with=self.engine)
            if escalation_triggers else None
        )
        with self.engine.begin() as connection:
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
                    command="analyze",
                    rule_invocations={"items": rule_invocations},
                    escalation_triggers=escalation_triggers
                )
                .returning(run_records.c.run_id)
            ).scalar_one()
            if review_queue is not None:
                connection.execute(
                    insert(review_queue).values(
                        incident_id=incident_id,
                        triggers=escalation_triggers
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

    def list_pending(self) -> list[ReviewQueueRecord]:
        columns = [self.table.c[name] for name in ReviewQueueRecord.model_fields]
        statement = select(*columns).where(self.table.c.status == "pending").order_by(self.table.c.created_at)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [ReviewQueueRecord.model_validate(dict(row)) for row in rows]

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
class SeedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysts_added: int
    grants_added: int
    incidents_added: int

class SeedRepository(_Repository):
    def __init__(self, dsn: str | None = None) -> None:
        super().__init__("incidents", dsn)
        metadata = MetaData()
        self.analysts = Table("analysts", metadata, autoload_with=self.engine)
        self.grants = Table("grants", metadata, autoload_with=self.engine)

    def seed(
        self,
        analysts: list[dict[str, Any]],
        grants: list[dict[str, Any]],
        incidents: list[dict[str, Any]]
    ) -> SeedSummary:
        added = {"analysts": 0, "grants": 0, "incidents": 0}
        with self.engine.begin() as connection:
            for analyst in analysts:
                statement = pg_insert(self.analysts).values(**analyst).on_conflict_do_nothing(
                    index_elements=[self.analysts.c.analyst_id]
                )
                added["analysts"] += connection.execute(statement).rowcount
            for grant in grants:
                statement = pg_insert(self.grants).values(**grant).on_conflict_do_nothing(
                    index_elements=[self.grants.c.analyst_id, self.grants.c.establishment]
                )
                added["grants"] += connection.execute(statement).rowcount
            for incident in incidents:
                statement = pg_insert(self.table).values(**incident).on_conflict_do_nothing(
                    index_elements=[self.table.c.incident_id]
                )
                added["incidents"] += connection.execute(statement).rowcount
        return SeedSummary(
            analysts_added=added["analysts"],
            grants_added=added["grants"],
            incidents_added=added["incidents"]
        )