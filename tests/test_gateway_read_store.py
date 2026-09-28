"""The Gateway read tools against Postgres: the session binds the subject and every call rechecks the grant."""

from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.repository import GatewayReadRepository, SessionRepository
from fieldsight.tool_service import ToolDenied
from fieldsight.tool_store import GatewayReadStore

DIMENSIONS = 1536


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (DIMENSIONS - len(leading)))]


@pytest.fixture
def world():
    """Two establishments; the analyst is granted only NORTH. conftest truncates incidents and sessions, not these."""
    repo = GatewayReadRepository()
    analysts = Table("analysts", MetaData(), autoload_with=repo.engine)
    north, south = f"North {uuid4()}", f"South {uuid4()}"
    email = f"analyst-{uuid4()}@example.invalid"
    with repo.engine.begin() as connection:
        analyst = connection.execute(insert(analysts).values(email=email, name="analyst").returning(analysts.c.analyst_id)).scalar_one()
        connection.execute(insert(repo.grants).values(analyst_id=analyst, establishment=north))

        def incident(establishment, embedding, *, closed=True, narrative="Worker slipped on wet stairs."):
            return connection.execute(
                insert(repo.table).values(
                    establishment=establishment, normalized_fields={"days_away": 2}, narrative=narrative,
                    embedding=embedding, outcome={"recordable": True} if closed else None, deciding_rule="R1" if closed else None,
                ).returning(repo.table.c.incident_id)
            ).scalar_one()

        subject = incident(north, _vector(1.0), closed=False)
        near = incident(north, _vector(0.9, 0.1), narrative="Slipped on a wet ladder rung.")
        far = incident(north, _vector(0.0, 1.0))
        other_site = incident(south, _vector(1.0))
        still_open = incident(north, _vector(1.0), closed=False)
        no_embedding = incident(north, None, closed=False)
    thread = f"{analyst}:{subject}:hazard_control"
    SessionRepository().create(thread, analyst, subject, "hazard_control")
    yield {"email": email, "analyst": analyst, "thread": thread, "subject": subject, "near": near, "far": far,
           "other_site": other_site, "still_open": still_open, "no_embedding": no_embedding, "south": south}
    with repo.engine.begin() as connection:
        connection.execute(delete(repo.grants).where(repo.grants.c.analyst_id == analyst))
        connection.execute(delete(repo.sessions).where(repo.sessions.c.analyst_id == analyst))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst))


def _denied(call, code):
    with pytest.raises(ToolDenied) as caught:
        call()
    assert caught.value.code == code


def test_extraction_reads_only_the_session_bound_incident(world):
    result = GatewayReadStore().extraction(world["email"], world["thread"])

    assert result == {"incident_id": str(world["subject"]), "normalized_fields": {"days_away": 2}}


def test_unbound_thread_or_wrong_caller_is_a_structured_denial(world):
    store = GatewayReadStore()

    _denied(lambda: store.extraction(world["email"], "some-other-thread"), "not_entitled")
    _denied(lambda: store.extraction("someone-else@example.invalid", world["thread"]), "not_entitled")


def test_no_grant_over_the_establishment_is_a_structured_denial_not_empty(world):
    store = GatewayReadStore()
    repo = store.repository
    thread = f"{world['analyst']}:{world['other_site']}:hazard_control"
    SessionRepository().create(thread, world["analyst"], world["other_site"], "hazard_control")

    _denied(lambda: store.extraction(world["email"], thread), "not_entitled")
    _denied(lambda: store.similar(world["email"], thread, 3), "not_entitled")
    assert repo.has_grant(world["analyst"], world["south"]) is False


def test_similar_returns_closed_granted_candidates_nearest_first(world):
    candidates = GatewayReadStore().similar(world["email"], world["thread"], 5)

    ids = [c.incident_id for c in candidates]
    assert ids == [world["near"], world["far"]]
    assert world["subject"] not in ids and world["other_site"] not in ids and world["still_open"] not in ids
    nearest = candidates[0]
    assert nearest.deciding_rule == "R1"
    assert nearest.outcome == {"recordable": True}
    assert nearest.matching_narrative_span == "Slipped on a wet ladder rung."
    assert candidates[0].similarity_score > candidates[1].similarity_score


def test_similar_respects_the_limit(world):
    assert len(GatewayReadStore().similar(world["email"], world["thread"], 1)) == 1


def test_similar_without_an_embedding_is_insufficient_data(world):
    thread = f"{world['analyst']}:{world['no_embedding']}:hazard_control"
    SessionRepository().create(thread, world["analyst"], world["no_embedding"], "hazard_control")

    _denied(lambda: GatewayReadStore().similar(world["email"], thread, 3), "insufficient_data")
