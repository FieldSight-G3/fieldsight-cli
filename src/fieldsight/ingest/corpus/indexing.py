""" stage corpus chunks in the KB's S3 data source, then sync the KB """

import time

from langchain_core.documents import Document

from ...aws.knowledge_base import get_sync, start_sync, write_chunk
from ...aws.s3 import delete_folder
from ...errors import IndexingError

KB_FOLDER = "kb/corpus"      # the data source's inclusion prefix
POLL_SECONDS = 5
MAX_CHECKS = 120


def stage_chunks(chunks: list[Document]) -> list[str]:
    """ replace a doc's chunk files (each with a .metadata.json); returns the chunk ids """

    folder = f"{KB_FOLDER}/{chunks[0].metadata['doc_id']}"
    delete_folder(folder)
    
    for chunk in chunks:
        write_chunk(folder, 
                    chunk.metadata["chunk_id"], 
                    chunk.page_content, 
                    chunk.metadata
                    )
        
    return [chunk.metadata["chunk_id"] for chunk in chunks]


def sync_knowledge_base() -> dict:
    """ sync the KB and wait; returns the job statistics """

    job_id = start_sync()
    for _ in range(MAX_CHECKS):
        job = get_sync(job_id)
        if job["status"] == "COMPLETE":
            return job["statistics"]
        if job["status"] in ("FAILED", "STOPPED"):
            raise IndexingError(f"KB sync {job_id} {job['status']}: {job.get('failureReasons')}")
        time.sleep(POLL_SECONDS)
    raise IndexingError(f"KB sync {job_id} still running after {MAX_CHECKS * POLL_SECONDS}s")
