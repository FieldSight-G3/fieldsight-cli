""" incident narrative embeddings: what find_similar_incidents searches, written when an incident is stored

    Titan v2 at 1024 dimensions, the size of incidents.embedding. Without one, the similar-incidents tool answers
    insufficient_data for that incident, so a failed embedding degrades precedent search instead of failing the write.
"""

import logging

from botocore.exceptions import BotoCoreError, ClientError

from ..aws import clients
from ..repository import IncidentRepository

logger = logging.getLogger(__name__)


def embed_narrative(narrative: str | None) -> list[float] | None:
    """ the narrative's embedding, or None when there is no narrative or Bedrock can't embed it now """

    if not narrative:
        return None
    try:
        return clients.embeddings().embed_query(narrative)
    except (BotoCoreError, ClientError, ValueError) as error:
        logger.warning("narrative not embedded; similar incidents unavailable for it: %s", type(error).__name__)
        return None


def embed_missing(incidents: IncidentRepository | None = None) -> int:
    """ embed every stored narrative that has no embedding yet; returns how many were embedded """

    incidents = incidents or IncidentRepository()
    rows = incidents.narratives_without_embedding()
    if not rows:
        return 0
    vectors = clients.embeddings().embed_documents([narrative for _, narrative in rows])
    incidents.set_embeddings({incident_id: vector for (incident_id, _), vector in zip(rows, vectors, strict=True)})
    return len(rows)
