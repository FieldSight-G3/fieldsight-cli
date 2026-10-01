""" embed every incident narrative that has no embedding yet, so find_similar_incidents has vectors to search

The seed and submit store narratives without embeddings, and the similar-incidents tool answers
insufficient_data until one exists. Titan v2 at 1024 dimensions, the size of incidents.embedding.

    python script/embed_incidents.py            # the database FIELDSIGHT_DATABASE_URL points at
"""

from sqlalchemy import select, update

from fieldsight.aws import clients
from fieldsight.repository.gateway import GatewayReadRepository

if __name__ == "__main__":
    repo = GatewayReadRepository()
    table = repo.table
    with repo.engine.connect() as connection:
        rows = connection.execute(
            select(table.c.incident_id, table.c.narrative)
            .where(table.c.embedding.is_(None), table.c.narrative.is_not(None))
        ).all()

    vectors = clients.embeddings().embed_documents([row.narrative for row in rows]) if rows else []
    with repo.engine.begin() as connection:
        for row, vector in zip(rows, vectors):
            connection.execute(update(table).where(table.c.incident_id == row.incident_id).values(embedding=vector))
    print(f"embedded {len(rows)} incident narratives")
