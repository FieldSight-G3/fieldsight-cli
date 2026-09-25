from uuid import UUID

from sqlalchemy import select

from fieldsight.repository import IncidentRepository
from fieldsight.seed import (
    ALICE,
    NORTH,
    SeedRepository,
    analysts,
    grants,
    historical_incidents,
    seed_demo,
    stable_id,
)


def test_seed_is_repeatable_and_covers_boundary_cases():
    cases = historical_incidents()
    assert len(cases) >= 12
    assert len({case["incident_id"] for case in cases}) == len(cases)
    first = seed_demo()
    second = seed_demo()
    assert first.incidents_added == len(cases)
    assert second.incidents_added == 0
    assert second.analysts_added == 0
    assert second.grants_added == 0
    stored = IncidentRepository().get(stable_id("fatality_day_30"))
    assert stored is not None
    assert stored.outcome is not None
    assert stored.outcome["reporting"] == "reportable"

def test_only_alice_has_the_north_establishment_grant():
    north_grants = [grant["analyst_id"] for grant in grants() if grant["establishment"] == NORTH]
    assert north_grants == [ALICE]

def test_seed_analysts_and_grants_have_unique_contact_and_identity():
    people = analysts()
    permissions = grants()
    assert len({person["email"] for person in people}) == len(people)
    assert len({grant["grant_id"] for grant in permissions}) == len(permissions)
    assert len({(grant["analyst_id"], grant["establishment"]) for grant in permissions}) == len(permissions)
    assert {grant["analyst_id"] for grant in permissions} <= {person["analyst_id"] for person in people}

def test_migrated_analyst_and_grant_rows_have_new_columns():
    seed_demo()
    repository = SeedRepository()
    with repository.engine.connect() as connection:
        alice = connection.execute(
            select(repository.analysts.c.name, repository.analysts.c.email, repository.analysts.c.created_at)
            .where(repository.analysts.c.analyst_id == ALICE)
        ).one()
        north = connection.execute(
            select(repository.grants.c.grant_id, repository.grants.c.created_at)
            .where(repository.grants.c.analyst_id == ALICE)
            .where(repository.grants.c.establishment == NORTH)
        ).one()
    assert alice.name == "Alice Example"
    assert alice.email == "alice@example.invalid"
    assert alice.created_at is not None
    assert isinstance(north.grant_id, UUID)
    assert north.created_at is not None
