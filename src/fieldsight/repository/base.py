"""The shared repository base: one engine and reflected table per repository, and the readiness probe."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from pgvector.sqlalchemy import (
    VECTOR as _VECTOR,  # noqa: F401 - registers vector type for reflection
)
from pydantic import BaseModel
from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.exc import OperationalError

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


def database_ready(engine: Any) -> bool:
    """The readiness probe: one round trip to Postgres. Connection failures mean not ready; anything else is a bug and raises."""
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError:
        return False
    return True
