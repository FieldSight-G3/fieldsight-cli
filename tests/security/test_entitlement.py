"""§11: in-process reads check the analyst's establishment grant on every call and deny with a structured result."""

from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.errors import ToolDenied
from fieldsight.repository import GatewayReadRepository, IncidentRepository
from fieldsight.security.entitlement import entitlement_denial, require_grant


@pytest.fixture
def world():
    """ one analyst granted NORTH only, with an incident at NORTH and one at SOUTH; conftest truncates neither analysts nor grants """

    repo = GatewayReadRepository()
    analysts = Table("analysts", MetaData(), autoload_with=repo.engine)
    north, south = f"North {uuid4()}", f"South {uuid4()}"
    with repo.engine.begin() as connection:
        analyst = connection.execute(
            insert(analysts).values(email=f"analyst-{uuid4()}@example.invalid", name="analyst").returning(analysts.c.analyst_id)
        ).scalar_one()
        connection.execute(insert(repo.grants).values(analyst_id=analyst, establishment=north))
    incidents = IncidentRepository()
    yield {"analyst": analyst, "granted": incidents.create(north, {"days_away": 1}), "other": incidents.create(south, {"days_away": 1})}
    with repo.engine.begin() as connection:
        connection.execute(delete(repo.grants).where(repo.grants.c.analyst_id == analyst))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst))


def _code(call) -> str:
    with pytest.raises(ToolDenied) as caught:
        call()
    return caught.value.code


def test_a_granted_analyst_passes(world):
    require_grant(world["analyst"], world["granted"])
    assert entitlement_denial({"analyst_id": str(world["analyst"]), "incident": {"incident_id": str(world["granted"])}}) is None


def test_no_grant_missing_incident_and_bad_ids_are_denied_by_code(world):
    assert _code(lambda: require_grant(world["analyst"], world["other"])) == "not_entitled"
    assert _code(lambda: require_grant(world["analyst"], uuid4())) == "not_found"
    assert _code(lambda: require_grant("not-a-uuid", world["granted"])) == "unauthenticated"
    assert _code(lambda: require_grant(uuid4(), world["granted"])) == "not_entitled"


def test_a_tool_gets_a_structured_denial_never_empty_results(world):
    denial = entitlement_denial({"analyst_id": str(world["analyst"]), "incident": {"incident_id": str(world["other"])}})

    assert denial == {"ok": False, "result": None, "error": {"code": "not_entitled", "message": "Caller has no grant for this establishment"}}
    assert entitlement_denial({"incident": {"incident_id": str(world["granted"])}})["error"]["code"] == "unauthenticated"
    assert entitlement_denial({"analyst_id": str(world["analyst"])})["error"]["code"] == "unauthenticated"


def test_the_grant_is_rechecked_on_every_call(world):
    repo = GatewayReadRepository()
    require_grant(world["analyst"], world["granted"], repository=repo)
    with repo.engine.begin() as connection:
        connection.execute(delete(repo.grants).where(repo.grants.c.analyst_id == world["analyst"]))

    assert _code(lambda: require_grant(world["analyst"], world["granted"], repository=repo)) == "not_entitled"
