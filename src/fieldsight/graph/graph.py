from uuid import UUID

from langgraph.graph import END, START, StateGraph

from ..checkpoint import Participant, open_thread, postgres_checkpointer
from ..config import settings
from ..schemas.incidents import NormalizedIncident
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


def run_graph(analyst_id: UUID, incident: NormalizedIncident, narrative: str | None) -> dict:
    """ one turn on the Coordinator's thread; the recursion limit is the independent hard cap on every loop """
    incident_id = UUID(incident.incident_id)
    open_thread(analyst_id, incident_id, Participant.REVIEWER)
    config = open_thread(analyst_id, incident_id, Participant.COORDINATOR)
    config["recursion_limit"] = settings.bounds.max_graph_recursion_depth
    return build_graph(postgres_checkpointer()).invoke(
        {"analyst_id": str(analyst_id), "incident": incident.model_dump(mode="json"), "narrative": narrative,
         "review_iterations": 0},
        config,
    )