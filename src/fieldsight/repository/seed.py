"""Idempotent seed inserts for the demo analysts, grants and historical incidents."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .base import _Repository


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
