from uuid import UUID

from langgraph.graph import END, START, StateGraph

from ..checkpoint import Participant, open_thread, postgres_checkpointer
from ..config import settings
from ..harness.run.workflow import Workflow
from ..repository import IncidentRepository
from ..schemas.incidents import NormalizedIncident
from ..types.run import WorkflowResult
from .nodes.eligibility import eligibility_check_node
from .nodes.review import reviewer_node, route_after_review
from .nodes.supervision import (
    coordinator_node,
    hazard_control_specialist_node,
    recordability_specialist_node,
    reportability_specialist_node,
    route_after_coordinator,
)
from .specialists import WORKERS
from .state import WorkflowState


def build_graph(checkpointer=None):
    graph = StateGraph(WorkflowState)
    
    # Nodes
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("recordability", recordability_specialist_node)
    graph.add_node("reportability", reportability_specialist_node)
    graph.add_node("hazard_control", hazard_control_specialist_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("eligibility_check", eligibility_check_node)


    # Edges
    graph.add_edge(START, "coordinator")
    graph.add_conditional_edges(
        "coordinator",
        route_after_coordinator,
        {
            "recordability": "recordability",
            "reportability": "reportability",
            "hazard_control": "hazard_control",
            "eligibility_check": "eligibility_check",
        },
    )
    for worker in WORKERS:
        graph.add_edge(worker, "reviewer")

    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "coordinator": "coordinator",
            "eligibility_check": "eligibility_check"
        },
    )
    graph.add_edge("eligibility_check", END)

    return graph.compile(name="coordinator", checkpointer=checkpointer)


# lists that live on the Coordinator's thread and grow every turn
TURN_LISTS = ("plans", "reviews", "tool_invocations", "model_calls")


def graph_workflow(analyst_id: UUID) -> Workflow:
    """ the Coordinator's graph as run_turn's workflow, for one analyst; each call is one turn on the Coordinator's thread """

    def workflow(incident: NormalizedIncident, question: str | None, correlation_id: str) -> WorkflowResult:
        incident_id = UUID(incident.incident_id)
        open_thread(analyst_id, incident_id, Participant.REVIEWER)
        config = open_thread(analyst_id, incident_id, Participant.COORDINATOR)
        config["recursion_limit"] = settings.bounds.max_graph_recursion_depth
        graph = build_graph(postgres_checkpointer())

        # this turn's entries are the ones past each list's length before the turn
        before = graph.get_state(config).values
        seen = {key: len(before.get(key, [])) for key in TURN_LISTS}
        state = graph.invoke({"analyst_id": str(analyst_id), "incident": incident.model_dump(mode="json"),
                              "narrative": IncidentRepository().get(incident_id).narrative,
                              "correlation_id": correlation_id, "review_iterations": 0}, config)
        turn = {key: state.get(key, [])[seen[key]:] for key in TURN_LISTS}

        reviews = turn["reviews"]
        return WorkflowResult(
            dossier=state.get("dossier") or {},
            workers_dispatched=sorted({d["worker"] for plan in turn["plans"] for d in plan["dispatches"]}),
            rule_invocations=state.get("rule_invocations") or [],
            reviewer_approved=(reviews[-1] is not None and reviews[-1].approved) if reviews else None,
            reviewer_iterations=state.get("review_iterations"),
            citations_supported=state.get("citations_supported"),
            blocked=state.get("blocked") or {},
            events=state.get("events") or [],
            plans=turn["plans"],
            tool_invocations=turn["tool_invocations"],
            model_calls=turn["model_calls"],
            reviewer_verdicts=reviews,
        )

    return workflow