""" ingest the corpus into the local pgvector Postgres instead of the KB: chunk, embed, store

    reuses the Textract output a cloud run saved under textract/<doc_id> in S3, so no Textract jobs run,
    and embeds with Titan v2 like the KB does. Needs AWS read access for S3 and Bedrock.

    run from the repo root with docker compose up and the schema migrated:
        docker compose up -d
        alembic upgrade head
        python script/ingest_corpus_local.py
"""

from fieldsight.aws import clients
from fieldsight.ingest.corpus.chain import chunk_chain
from fieldsight.ingest.corpus.chunking import CHUNK_CHARS, OVERLAP_CHARS
from fieldsight.ingest.corpus.sources import corpus_docs
from fieldsight.repository import CorpusChunkRecord, CorpusChunkRepository

if __name__ == "__main__":
    docs = corpus_docs()

    # chunk and embed every doc before writing, so one failure leaves the table untouched
    chunked = chunk_chain().batch(docs)
    embeddings = clients.embeddings()
    records = [
        [CorpusChunkRecord(**chunk.metadata, text=chunk.page_content, embedding=vector)
         for chunk, vector in zip(chunks, embeddings.embed_documents([chunk.page_content for chunk in chunks]))]
        for chunks in chunked
    ]

    repository = CorpusChunkRepository()
    for doc, doc_records in zip(docs, records):
        print(f"{doc['doc_id']}: {repository.replace_document(doc['doc_id'], doc_records)} chunks")
    print(f"chunk size {CHUNK_CHARS} chars, overlap {OVERLAP_CHARS}")
