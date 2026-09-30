"""§11: a correction to a run record is a new record referencing the original, never an edit in place."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from fieldsight.repository import IncidentRepository, RunRepository


@pytest.fixture
def original():
    incident_id = IncidentRepository().create("Substation 7", {"days_away": 3})
    runs = RunRepository()
    run_id = runs.create(uuid4(), "analyze", incident_id=incident_id, rule_invocations={"items": [{"rule_id": "R4"}]})
    return runs, run_id, incident_id


def test_a_correction_is_a_new_redacted_record_pointing_at_the_original(original):
    runs, run_id, incident_id = original
    fixed = {"items": [{"rule_id": "R4", "note": "phone 571-555-0142 on the form"}]}

    correction_id = runs.record_correction(run_id, "Day count used the wrong return date; confirmed by phone at 571-555-0142",
                                           uuid4(), rule_invocations=fixed)

    assert correction_id != run_id
    corrected = runs.get(correction_id)
    assert corrected is not None and corrected.command == "correction" and corrected.incident_id == incident_id
    assert "571-555-0142" not in str(corrected.rule_invocations)
    [listed] = runs.corrections_of(run_id)
    assert listed["run_id"] == correction_id and "571-555-0142" not in listed["correction_reason"]
    # the original is untouched
    kept = runs.get(run_id)
    assert kept is not None and kept.rule_invocations == {"items": [{"rule_id": "R4"}]}


def test_the_database_refuses_edits_and_deletes(original):
    runs, run_id, _ = original

    with pytest.raises(DBAPIError, match="append-only"), runs.engine.begin() as connection:
        connection.execute(update(runs.table).where(runs.table.c.run_id == run_id).values(command="edited"))
    with pytest.raises(DBAPIError, match="append-only"), runs.engine.begin() as connection:
        connection.execute(delete(runs.table).where(runs.table.c.run_id == run_id))
    kept = runs.get(run_id)
    assert kept is not None and kept.command == "analyze"


def test_a_correction_needs_a_reason_and_an_existing_original(original):
    runs, run_id, _ = original

    with pytest.raises(ValueError):
        runs.record_correction(run_id, "  ", uuid4())
    with pytest.raises(LookupError):
        runs.record_correction(uuid4(), "no such run", uuid4())
    # the schema itself pairs a reference with a reason
    with pytest.raises(IntegrityError), runs.engine.begin() as connection:
        connection.execute(insert(runs.table).values(correlation_id=uuid4(), command="correction", corrects_run_id=run_id))
    assert runs.corrections_of(run_id) == []


def test_corrections_are_listed_oldest_first(original):
    runs, run_id, _ = original
    first = runs.record_correction(run_id, "first fix", uuid4())
    second = runs.record_correction(run_id, "second fix", uuid4())

    assert [row["run_id"] for row in runs.corrections_of(run_id)] == [first, second]
