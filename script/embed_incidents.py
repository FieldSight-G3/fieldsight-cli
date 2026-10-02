""" embed every incident narrative that has no embedding yet, so find_similar_incidents has vectors to search

submit and the seed embed as they write; this backfills rows written before they did, or whose embedding failed.

    python script/embed_incidents.py            # the database FIELDSIGHT_DATABASE_URL points at
"""

from fieldsight.ingest.embedding import embed_missing

if __name__ == "__main__":
    print(f"embedded {embed_missing()} incident narratives")
