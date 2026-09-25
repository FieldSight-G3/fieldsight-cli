""" crack PDFs with Textract and return their blocks """

import time

from ..aws.textract import get_analysis_status, get_blocks, start_analysis
from ..errors import ExtractionError

POLL_SECONDS = 1
MAX_CHECKS = 180


def wait_until_done(job_id: str) -> str:
    """ poll until the job finishes; returns its final status """
    for _ in range(MAX_CHECKS):
        status = get_analysis_status(job_id)

        if status != "IN_PROGRESS":
            return status

        time.sleep(POLL_SECONDS)

    raise ExtractionError(f"Textract job {job_id} still running after {MAX_CHECKS * POLL_SECONDS}s")


def crack(key: str, token: str | None = None) -> list[dict]:
    """ Textract a PDF in S3 and return its blocks; a file-hash token lets a re-run reuse the job """

    return finish(key, start_analysis(key, token=token))


def finish(key: str, job_id: str) -> list[dict]:
    """ wait for a started job and return its blocks, so callers can start several first """

    status = wait_until_done(job_id)

    # PARTIAL_SUCCESS still has most pages, so keep it
    if status not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
        raise ExtractionError(f"Textract job for {key} finished with status {status}")

    return get_blocks(job_id)
