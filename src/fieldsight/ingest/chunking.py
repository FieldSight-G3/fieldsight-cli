""" corpus ingestion: which documents make up the corpus, and where they sit in S3 """

import json

from ..aws.s3 import pdf_key
from ..config import CORPUS_SOURCES


def corpus_doc_ids() -> list[str]:
    """ the doc ids listed in corpus/sources.json """

    sources = json.loads(CORPUS_SOURCES.read_text(encoding="utf-8"))
    return [doc["doc_id"] for doc in sources["documents"]]


def load_corpus() -> list[str]:
    """ the S3 key of every corpus doc, in the same order as corpus_doc_ids() """

    return [pdf_key(doc_id, corpus=True) for doc_id in corpus_doc_ids()]
