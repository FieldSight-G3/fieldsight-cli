""" a reused thread (the Reviewer's) never carries tool calls that didn't run into its next run """

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from fieldsight.aws import clients
from fieldsight.graph import specialists


@tool
def search(query: str) -> str:
    """ Search the corpus. """
    return "result"


class RecordingModel:
    """ stands in for Bedrock: replays one reply per call and keeps what each call was sent """

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.sent.append(messages)
        return self.replies.pop(0)


def test_tool_calls_the_cap_cut_off_are_answered_before_the_thread_runs_again(monkeypatch):
    asks = AIMessage("", tool_calls=[{"name": "search", "args": {"query": "1904.39"}, "id": "t1"}])
    model = RecordingModel([asks, AIMessage("Approved.")])
    monkeypatch.setattr(clients, "chat_model", lambda: model)
    # one round: the first run asks for a tool, and the cap ends it before the tool runs
    monkeypatch.setattr(specialists, "MAX_SPECIALIST_TOOL_ROUNDS", 1)
    reviewer = specialists.build_specialist("reviewer", "Review the dossier.", [search], InMemorySaver())
    thread = {"configurable": {"thread_id": "analyst:incident:reviewer"}}

    reviewer.invoke({"task": "first review", "rounds": 0, "proposal": None}, thread)
    reviewer.invoke({"task": "second review", "rounds": 0, "proposal": None}, thread)

    sent = model.sent[1]
    at = next(index for index, message in enumerate(sent) if isinstance(message, AIMessage) and message.tool_calls)
    assert isinstance(sent[at + 1], ToolMessage) and sent[at + 1].tool_call_id == "t1"
    assert sent[at + 1].content == specialists.NOT_RUN
