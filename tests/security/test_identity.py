"""Identity: a caller proof maps to exactly one enrolled analyst, and never from a request field."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, insert

from fieldsight.errors import ToolDenied
from fieldsight.security import iam_caller_proof
from fieldsight.security.identity import production_resolver

SESSION = "runtime-session-0123456789abcdef0123456789"


@pytest.fixture
def enrolled(monkeypatch):
    """ an analyst enrolled under one role; the STS round trip is replaced by a check of the proof and its session binding """

    from fieldsight.repository import AnalystRepository

    role = f"arn:aws:iam::123456789012:role/FieldSightTest{uuid4().hex[:8]}"
    analysts = AnalystRepository()
    with analysts.engine.begin() as connection:
        analyst = connection.execute(
            insert(analysts.table).values(email=f"a-{uuid4()}@example.invalid", name="a", iam_role_arn=role)
            .returning(analysts.table.c.analyst_id)
        ).scalar_one()
    monkeypatch.setattr(iam_caller_proof, "enrolled_analyst_roles", lambda configured: (frozenset({role}), "123456789012"))

    def verify(proof, thread_id, region, account_id, allowed):
        if proof != "good" or thread_id != SESSION or role not in allowed:
            raise ToolDenied("unauthenticated", "Valid enrolled IAM role proof is required")
        return role

    monkeypatch.setattr(iam_caller_proof, "verify_proof", verify)
    yield analyst
    with analysts.engine.begin() as connection:
        connection.execute(delete(analysts.table).where(analysts.table.c.analyst_id == analyst))


def test_the_production_resolver_maps_the_proven_role_to_the_analyst(enrolled, monkeypatch):
    resolve = production_resolver()

    assert resolve("good", SESSION) == enrolled
    with pytest.raises(ToolDenied):
        resolve("forged", SESSION)
    with pytest.raises(ToolDenied):
        resolve("good", "another-session-0123456789abcdef012345")

    monkeypatch.setattr(iam_caller_proof, "verify_proof", lambda *args: "arn:aws:iam::123456789012:role/NotEnrolled")
    with pytest.raises(ToolDenied) as denied:
        production_resolver()("good", SESSION)
    assert denied.value.code == "not_entitled"
