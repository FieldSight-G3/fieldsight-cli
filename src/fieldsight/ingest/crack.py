""" crack PDFs with Textract: wait out the job, then hand back its blocks """

import time

from ..aws.textract import get_analysis_status, get_blocks, start_analysis
from ..errors import ExtractionError

POLL_SECONDS = 1
MAX_CHECKS = 180


def wait_until_done(job_id: str) -> str:
    """ check the job every second until Textract is done with it, returns the final status """
    for _ in range(MAX_CHECKS):
        status = get_analysis_status(job_id)

        if status != "IN_PROGRESS":
            return status

        time.sleep(POLL_SECONDS)

    raise ExtractionError(f"Textract job {job_id} still running after {MAX_CHECKS * POLL_SECONDS}s")


def crack(key: str) -> list[dict]:
    """ run Textract over a PDF already in S3 and return all of its blocks """

    job_id = start_analysis(key)
    status = wait_until_done(job_id)

    # PARTIAL_SUCCESS still gives us most of the pages, so don't throw it away
    if status not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
        raise ExtractionError(f"Textract job for {key} finished with status {status}")

    return get_blocks(job_id)


