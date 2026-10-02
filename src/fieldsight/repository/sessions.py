"""Checkpointer sessions: one thread per (analyst, incident, participant), bound once and reused."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .base import _Repository


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    analyst_id: UUID
    incident_id: UUID
    participant: str
    created_at: datetime
    cost_usd: float

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

    def session_cost(self, thread_id: str) -> float:
        """ the dollars the session has spent across every command so far; 0 for a session not started yet """

        statement = select(self.table.c.cost_usd).where(self.table.c.thread_id == thread_id)
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() or 0.0

    def add_cost(self, thread_id: str, analyst_id: UUID, incident_id: UUID, participant: str, amount: float) -> None:
        """ add one turn's spend in a single statement, creating the session row if it's new, so no spend is lost """

        statement = pg_insert(self.table).values(
            thread_id=thread_id,
            analyst_id=analyst_id,
            incident_id=incident_id,
            participant=participant,
            cost_usd=amount,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["thread_id"], set_={"cost_usd": self.table.c.cost_usd + statement.excluded.cost_usd})
        with self.engine.begin() as connection:
            connection.execute(statement)
