import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, TypedDict
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from fieldsight import checkpoint
from fieldsight.checkpoint import (
    Participant,
    open_thread,
    thread_id,
)
from fieldsight.config import settings
from fieldsight.graph.specialists import WORKERS
from fieldsight.repository import IncidentRepository, SessionRepository

ANALYST = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ANALYST = UUID("22222222-2222-2222-2222-222222222222")
INCIDENT = UUID("33333333-3333-3333-3333-333333333333")
OTHER_INCIDENT = UUID("44444444-4444-4444-4444-444444444444")


def test_thread_id_keeps_the_reviewer_format():
    assert thread_id(ANALYST, INCIDENT, Participant.REVIEWER) == f"{ANALYST}:{INCIDENT}:reviewer"


def test_thread_id_is_stable_across_input_types():
    assert thread_id(ANALYST, INCIDENT, "reviewer") == thread_id(str(ANALYST), str(INCIDENT), Participant.REVIEWER)


def test_every_participant_gets_its_own_thread():
    threads = {thread_id(ANALYST, INCIDENT, participant) for participant in Participant}
    assert len(threads) == len(Participant)


def test_analyst_and_incident_each_change_the_thread():
    base = thread_id(ANALYST, INCIDENT, Participant.RECORDABILITY)
    assert thread_id(OTHER_ANALYST, INCIDENT, Participant.RECORDABILITY) != base
    assert thread_id(ANALYST, OTHER_INCIDENT, Participant.RECORDABILITY) != base


def test_every_worker_is_a_participant():
    assert set(WORKERS) <= {participant.value for participant in Participant}


def test_unknown_participant_is_rejected():
    with pytest.raises(ValueError):
        thread_id(ANALYST, INCIDENT, "revewer")


@pytest.mark.parametrize("bad", ["", "a:b", "has space", "caf\u00e9"])
def test_bad_component_is_rejected(bad):
    with pytest.raises(ValueError):
        thread_id(bad, INCIDENT, Participant.COORDINATOR)

def test_open_thread_registers_once_and_returns_the_run_config():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})

    first = open_thread(ANALYST, incident_id, Participant.REVIEWER)
    second = open_thread(ANALYST, incident_id, "reviewer")

    assert first == second == {"configurable": {"thread_id": f"{ANALYST}:{incident_id}:reviewer"}}
    record = SessionRepository().get(first["configurable"]["thread_id"])
    assert (record.analyst_id, record.incident_id, record.participant) == (ANALYST, incident_id, "reviewer")


def test_open_thread_gives_each_participant_its_own_row():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})

    threads = [open_thread(ANALYST, incident_id, participant)["configurable"]["thread_id"] for participant in Participant]

    sessions = SessionRepository()
    assert [sessions.get(thread).participant for thread in threads] == [participant.value for participant in Participant]

def test_conninfo_is_libpq_form_and_keeps_the_local_password(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://fieldsight:secret@localhost:5434/fieldsight")
    monkeypatch.setattr(settings, "database_iam_auth", False)

    assert checkpoint.conninfo() == "postgresql://fieldsight:secret@localhost:5434/fieldsight"
    kwargs = checkpoint.connection_kwargs()
    assert "password" not in kwargs and "sslmode" not in kwargs


class FakeRds:
    """ stands in for the RDS client: a new token on every call """

    def __init__(self):
        self.calls = []

    def generate_db_auth_token(self, **kwargs):
        self.calls.append(kwargs)
        return f"token-{len(self.calls)}"


def test_iam_auth_drops_the_password_and_mints_a_fresh_token_per_connection(monkeypatch):
    rds = FakeRds()
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://fieldsight:unused@db.example.rds.amazonaws.com/fieldsight")
    monkeypatch.setattr(settings, "database_iam_auth", True)
    monkeypatch.setattr(checkpoint.clients, "rds", lambda: rds)

    assert checkpoint.conninfo() == "postgresql://fieldsight@db.example.rds.amazonaws.com/fieldsight"
    first, second = checkpoint.connection_kwargs(), checkpoint.connection_kwargs()
    assert (first["password"], second["password"]) == ("token-1", "token-2")
    assert first["sslmode"] == "require"
    assert rds.calls[0] == {
        "DBHostname": "db.example.rds.amazonaws.com", "Port": 5432, "DBUsername": "fieldsight", "Region": settings.aws_region,
    }


def test_postgres_checkpointer_is_shared_and_ready():
    saver = checkpoint.postgres_checkpointer()

    assert checkpoint.postgres_checkpointer() is saver
    assert saver.get_tuple({"configurable": {"thread_id": "no-such-thread"}}) is None

class Notes(TypedDict):
    notes: Annotated[list[str], operator.add]


def note_graph(saver):
    """ a one-node graph whose whole state is a list of notes: each run appends its input to the thread's history """

    graph = StateGraph(Notes)
    graph.add_node("write", lambda state: {})
    graph.add_edge(START, "write")
    graph.add_edge("write", END)
    return graph.compile(checkpointer=saver)


def test_participants_on_one_incident_keep_separate_memory_in_postgres():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})
    analyst_id = uuid4()
    graph = note_graph(checkpoint.postgres_checkpointer())

    worker = open_thread(analyst_id, incident_id, Participant.REPORTABILITY)
    reviewer = open_thread(analyst_id, incident_id, Participant.REVIEWER)

    graph.invoke({"notes": ["worker tool-call transcript"]}, worker)
    graph.invoke({"notes": ["dossier v1"]}, reviewer)
    graph.invoke({"notes": ["dossier v2"]}, reviewer)

    # the Reviewer's thread resumed across runs and never saw the worker's transcript
    assert graph.get_state(reviewer).values["notes"] == ["dossier v1", "dossier v2"]
    assert graph.get_state(worker).values["notes"] == ["worker tool-call transcript"]

    # a fresh saver on its own connection reads the same state back: it lives in Postgres, as a later CLI command needs
    with PostgresSaver.from_conn_string(checkpoint.conninfo()) as fresh:
        assert note_graph(fresh).get_state(reviewer).values["notes"] == ["dossier v1", "dossier v2"]

def test_concurrent_callers_share_one_checkpointer(monkeypatch):
    # start from "not built yet", so all eight threads race to build it
    monkeypatch.setattr(checkpoint, "_SAVER", None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        savers = list(pool.map(lambda _: checkpoint.postgres_checkpointer(), range(8)))

    assert len({id(saver) for saver in savers}) == 1