""" shapes of the dossier the Reviewer judges: plain dicts assembled from the workers' outputs, never a transcript """

from typing import TypedDict


class DossierLeg(TypedDict):
    """ one worker's part of the dossier: its goal, its accepted proposal, and only what that proposal rests on """

    task: str                   # the goal it was given; the Coordinator narrows it on re-dispatch
    proposal: dict | None       # None when the worker got no proposal accepted
    decisions: dict[str, dict]  # the latest decision per rule it ran, so threshold outcomes stay attributed
    cited: dict[str, dict]      # the retrieved hits for the proposal's chunk ids, text included


# keyed by worker; parallel legs merge, and a re-dispatched leg replaces the rejected one
Dossier = dict[str, DossierLeg]
