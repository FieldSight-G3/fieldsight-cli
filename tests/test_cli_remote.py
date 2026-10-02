"""The CLI's remote mode: analyze and ask go to the deployed Runtime when FIELDSIGHT_RUNTIME_ID is set."""

from uuid import uuid4

from fieldsight.interfaces import cli, remote
from fieldsight.types.run import TurnRun


def a_run(command: str) -> TurnRun:
    return TurnRun(run_id=uuid4(), correlation_id=uuid4(), command=command, route="answer_from_retrieval",
                   answer="an answer [1]")


def test_the_session_is_the_same_for_the_same_analyst_and_incident_and_long_enough():
    first = remote.session_for("arn:aws:sts::1:assumed-role/fieldsight-analyst/a", "inc-1")

    assert first == remote.session_for("arn:aws:sts::1:assumed-role/fieldsight-analyst/a", "inc-1")
    assert first != remote.session_for("arn:aws:sts::1:assumed-role/fieldsight-analyst/a", "inc-2")
    assert len(first) >= 33


def test_with_a_runtime_id_ask_goes_to_the_runtime_and_never_runs_locally(monkeypatch):
    sent = []
    monkeypatch.setenv(remote.RUNTIME_ID, "fieldsight_runtime-abc")
    monkeypatch.setattr(remote, "turn", lambda request, runtime: sent.append((request, runtime)) or a_run("ask"))
    monkeypatch.setattr(cli.wiring, "turn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran locally")))

    args = cli.parser().parse_args(["ask", "inc-1", "Is that first aid?"])
    printed = cli.COMMANDS["ask"](args, None)

    assert sent == [({"command": "ask", "incident_id": "inc-1", "question": "Is that first aid?"}, "fieldsight_runtime-abc")]
    assert "an answer" in printed


def test_without_a_runtime_id_the_turn_runs_here(monkeypatch):
    monkeypatch.delenv(remote.RUNTIME_ID, raising=False)
    monkeypatch.setattr(cli.wiring, "turn", lambda request, analyst_id: a_run(request["command"]))

    assert "an answer" in cli.COMMANDS["analyze"](cli.parser().parse_args(["analyze", "inc-1"]), uuid4())


def test_a_runtime_result_becomes_the_turn_run_a_local_turn_returns():
    run = a_run("analyze")

    assert TurnRun.model_validate(run.model_dump(mode="json")) == run
