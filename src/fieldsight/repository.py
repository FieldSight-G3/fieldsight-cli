from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import BaseModel, ConfigDict

from fieldsight.config import settings


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


class IncidentRepository:
    """Owns every query against the incidents table. No other module
    should import psycopg or execute SQL against this table directly."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url

    def create(
        self,
        establishment: str,
        normalized_fields: dict[str, Any],
        narrative: str | None = None,
    ) -> UUID:
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incidents (establishment, normalized_fields, narrative)
                    VALUES (%s, %s, %s)
                    RETURNING incident_id
                    """,
                    (establishment, Json(normalized_fields), narrative),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]

    def get(self, incident_id: UUID) -> IncidentRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT incident_id, establishment, submitted_at,
                           normalized_fields, narrative, outcome,
                           deciding_rule, status
                    FROM incidents
                    WHERE incident_id = %s
                    """,
                    (incident_id,),
                )
                row = cur.fetchone()
                return IncidentRecord(**row) if row else None


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


class RunRecordRepository:
    """Owns every query against the run_records table."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url

    def create(
        self,
        correlation_id: UUID,
        command: str,
        incident_id: UUID | None = None,
        workers_dispatched: dict[str, Any] | None = None,
        tool_invocations: dict[str, Any] | None = None,
        rule_invocations: dict[str, Any] | None = None,
        escalation_triggers: dict[str, Any] | None = None,
        model_calls: dict[str, Any] | None = None,
    ) -> UUID:
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_records (
                        correlation_id, incident_id, command,
                        workers_dispatched, tool_invocations, rule_invocations,
                        escalation_triggers, model_calls
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING run_id
                    """,
                    (
                        correlation_id,
                        incident_id,
                        command,
                        Json(workers_dispatched) if workers_dispatched is not None else None,
                        Json(tool_invocations) if tool_invocations is not None else None,
                        Json(rule_invocations) if rule_invocations is not None else None,
                        Json(escalation_triggers) if escalation_triggers is not None else None,
                        Json(model_calls) if model_calls is not None else None,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]

    def get(self, run_id: UUID) -> RunRecordRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id, correlation_id, incident_id, command,
                           workers_dispatched, tool_invocations, rule_invocations,
                           escalation_triggers, model_calls, created_at
                    FROM run_records
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
                return RunRecordRecord(**row) if row else None


class ReviewQueueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_id: UUID
    incident_id: UUID
    triggers: dict[str, Any]
    status: str
    decision: dict[str, Any] | None
    created_at: datetime


class ReviewQueueRepository:
    """Owns every query against the review_queue table."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url

    def create(self, incident_id: UUID, triggers: dict[str, Any]) -> UUID:
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_queue (incident_id, triggers)
                    VALUES (%s, %s)
                    RETURNING queue_id
                    """,
                    (incident_id, Json(triggers)),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]

    def get(self, queue_id: UUID) -> ReviewQueueRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT queue_id, incident_id, triggers, status, decision, created_at
                    FROM review_queue
                    WHERE queue_id = %s
                    """,
                    (queue_id,),
                )
                row = cur.fetchone()
                return ReviewQueueRecord(**row) if row else None

    def list_pending(self) -> list[ReviewQueueRecord]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT queue_id, incident_id, triggers, status, decision, created_at
                    FROM review_queue
                    WHERE status = 'pending'
                    ORDER BY created_at
                    """
                )
                rows = cur.fetchall()
                return [ReviewQueueRecord(**row) for row in rows]


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    analyst_id: UUID
    incident_id: UUID
    participant: str
    created_at: datetime


class SessionRepository:
    """Owns every query against the sessions table."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url

    def create(
        self,
        thread_id: str,
        analyst_id: UUID,
        incident_id: UUID,
        participant: str,
    ) -> str:
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (thread_id, analyst_id, incident_id, participant)
                    VALUES (%s, %s, %s, %s)
                    RETURNING thread_id
                    """,
                    (thread_id, analyst_id, incident_id, participant),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0]

    def get(self, thread_id: str) -> SessionRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT thread_id, analyst_id, incident_id, participant, created_at
                    FROM sessions
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = cur.fetchone()
                return SessionRecord(**row) if row else None