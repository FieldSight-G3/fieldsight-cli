from fieldsight.repository import IncidentRepository
from fieldsight.seed import ALICE, NORTH, grants, historical_incidents, seed_demo, stable_id

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