"""The specialist loop: a determination is refused where the worker can still rephrase it, and a reused thread
sends the model only the current run."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from fieldsight.graph import specialists
from fieldsight.tools.tools import propose


class Draft(BaseModel):
    rationale: str


def status(command) -> str:
    return command.update["messages"][0].content


def test_a_rationale_stating_a_determination_is_sent_back_to_rephrase():
    command = propose(Draft(rationale="The incident is recordable [1]."), [], "call-1")
    assert '"rejected"' in status(command) and "The incident is recordable" in status(command)
    assert "proposal" not in command.update


def test_a_rationale_attributing_the_outcome_to_its_rule_is_accepted():
    command = propose(Draft(rationale="R1 found the 1904.7 recording criteria met [1]."), [], "call-1")
    assert '"accepted"' in status(command) and command.update["proposal"]


class Model:
    """ records what each call sent, and answers without asking for tools """

    def __init__(self) -> None:
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content="done")


def test_a_reused_thread_sends_only_the_current_run_with_the_current_brief(monkeypatch):
    model = Model()
    monkeypatch.setattr(specialists.clients, "chat_model", lambda: model)
    reviewer = specialists.build_specialist("reviewer", "the brief", [], InMemorySaver())
    config = {"configurable": {"thread_id": "analyst:incident:reviewer"}}

    reviewer.invoke({"task": "first dossier", "rounds": 0, "proposal": None}, config)
    reviewer.invoke({"task": "second dossier", "rounds": 0, "proposal": None}, config)

    sent = model.calls[-1]
    assert isinstance(sent[0], SystemMessage) and sent[0].content == "the brief"
    assert [m.content for m in sent[1:] if isinstance(m, HumanMessage)] == ["second dossier"]
    # the thread itself still keeps both runs
    stored = reviewer.get_state(config).values["messages"]
    assert [m.content for m in stored if isinstance(m, HumanMessage)] == ["first dossier", "second dossier"]


class Searching(Model):
    """ asks for a search every call, so the run reaches the wind-down """

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content="", tool_calls=[{"name": "noop", "args": {}, "id": f"c{len(self.calls)}"}])


def test_the_wind_down_goes_in_the_system_message_never_a_user_turn(monkeypatch):
    from langchain_core.tools import tool

    @tool
    def noop() -> str:
        """ does nothing """
        return "ok"

    model = Searching()
    monkeypatch.setattr(specialists.clients, "chat_model", lambda: model)
    monkeypatch.setattr(specialists, "MAX_SPECIALIST_TOOL_ROUNDS", 4)
    worker = specialists.build_specialist("recordability", "the brief", [noop])
    worker.invoke({"task": "the task", "rounds": 0, "proposal": None})

    # the Prompt Attacks filter screens user turns, and blocked the warning there
    assert all(specialists.WIND_DOWN not in str(m.content) for call in model.calls for m in call
               if isinstance(m, HumanMessage))
    assert specialists.WIND_DOWN in model.calls[-1][0].content and specialists.WIND_DOWN not in model.calls[0][0].content


def test_a_re_dispatch_sends_the_reviewer_feedback_in_the_system_message(monkeypatch):
    model = Model()
    monkeypatch.setattr(specialists.clients, "chat_model", lambda: model)
    worker = specialists.build_specialist("recordability", "the brief", [])
    worker.invoke({"task": "the goal", "feedback": "Your proposal was rejected: fix the citation", "rounds": 0,
                   "proposal": None})

    [call] = model.calls
    # the Prompt Attacks filter screens user turns; there the feedback blocked the re-dispatch's first call
    assert "Your proposal was rejected" in call[0].content
    assert [m.content for m in call if isinstance(m, HumanMessage)] == ["the goal"]
