""" crack the corpus PDFs with Textract, saving the output under textract/<doc_id> for the loader """

import hashlib

from ...aws.s3 import upload
from ...aws.textract import start_analysis
from ...errors import ExtractionError
from ...types.corpus import CorpusDoc
from ..crack import wait_until_done
from .sources import pdf_key, pdf_path

CORPUS_FEATURES = ["TABLES", "LAYOUT"]


def start_crack(doc: CorpusDoc) -> str:
    """ upload the doc's PDF and start its Textract job; the file's hash makes a re-run hand back the same job """

    upload(pdf_path(doc), pdf_key(doc))
    token = hashlib.sha256(pdf_path(doc).read_bytes()).hexdigest()
    return start_analysis(
        pdf_key(doc), 
        output_prefix=f"textract/{doc['doc_id']}", 
        features=CORPUS_FEATURES, 
        token=token
        )


def crack_corpus(docs: list[CorpusDoc]) -> None:
    """ start every doc's job first so they run side by side, then wait on each """

    jobs = {doc["doc_id"]: start_crack(doc) for doc in docs}

    # the corpus has to be complete, so a partial result counts as a failure here
    failed = [doc_id for doc_id, job_id in jobs.items() if wait_until_done(job_id) != "SUCCEEDED"]
    if failed:
        raise ExtractionError(f"Textract didn't fully succeed for: {', '.join(failed)}")
