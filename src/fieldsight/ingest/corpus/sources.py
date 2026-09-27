""" corpus documents and their local and S3 locations """

import json
from pathlib import Path

from ...types.corpus import CORPUS_DOC, CorpusDoc

CORPUS_SOURCES = Path(__file__).resolve().parents[4] / "corpus" / "sources.json"


def corpus_docs() -> list[CorpusDoc]:
    """ every document listed in corpus/sources.json """

    sources = json.loads(CORPUS_SOURCES.read_text(encoding="utf-8"))
    return [CORPUS_DOC.validate_python(doc) for doc in sources["documents"]]


def letters() -> dict[str, str]:
    """ corpus letters of interpretation, date (YYYY-MM-DD) to title """

    sources = json.loads(CORPUS_SOURCES.read_text(encoding="utf-8"))
    return {item["label"]: item["title"]
            for doc in sources["documents"] if doc["doc_type"] == "interpretation"
            for item in doc.get("items", [])}


def pdf_path(doc: CorpusDoc) -> Path:
    """ the doc's excerpted PDF in the repo, corpus/pdf/<doc_id>.pdf """

    return CORPUS_SOURCES.parent / "pdf" / f"{doc['doc_id']}.pdf"


def pdf_key(doc: CorpusDoc) -> str:
    """ where the doc's PDF sits in S3 for Textract """

    return f"corpus/{doc['doc_id']}.pdf"
