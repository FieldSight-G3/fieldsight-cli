"""Analysts: the enrolled IAM role each maps to, and the establishments they hold grants for."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import MetaData, Table, select, update

from .base import _Repository


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
