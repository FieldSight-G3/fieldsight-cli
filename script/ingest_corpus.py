""" ingest the corpus into the KB: crack, chunk, stage, sync

    run from the repo root when corpus/ changes:  python script/ingest_corpus.py
"""

from fieldsight.ingest.corpus.chain import chunk_chain
from fieldsight.ingest.corpus.chunking import CHUNK_CHARS, OVERLAP_CHARS
from fieldsight.ingest.corpus.cracking import crack_corpus
from fieldsight.ingest.corpus.indexing import stage_chunks, sync_knowledge_base
from fieldsight.ingest.corpus.sources import corpus_docs

if __name__ == "__main__":
    docs = corpus_docs()
    crack_corpus(docs)

    # chunk every doc before writing, so one failure leaves the data source untouched
    chunked = chunk_chain().batch(docs)

    for doc, chunks in zip(docs, chunked):
        stage_chunks(chunks)
        print(f"{doc['doc_id']}: {len(chunks)} chunks")
    print(f"chunk size {CHUNK_CHARS} chars, overlap {OVERLAP_CHARS}")
    print(sync_knowledge_base())
