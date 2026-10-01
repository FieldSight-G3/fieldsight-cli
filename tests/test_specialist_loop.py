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
