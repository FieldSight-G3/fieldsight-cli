""" the eligibility check: where the Coordinator's graph ends and hands the finished cycle back to the harness

    It writes nothing. run_turn evaluates escalation over the whole turn and saves once: the run record, and the
    review queue row with its dossier snapshot (ReviewSnapshot.of) when a trigger fired. Writing here as well gave
    every escalated turn two run records and two queue rows, one of them unreviewable.
"""


def eligibility_check_node(state: dict) -> dict:
    """ route_after_review sends every finished cycle here; the dossier and reviews already in state are the result """

    return {}
