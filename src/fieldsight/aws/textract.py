""" run Amazon Textract over PDFs sitting in S3

    multi-page PDFs have to go through the async API: start a job, check its
    status until it's done, then page through the blocks Textract hands back
"""

from ..config import BUCKET_NAME
from .client import get_client


def start_analysis(key: str, output_prefix: str | None = None) -> str:
    """ start an async Textract job for a PDF already in S3, returns the job id

        with output_prefix, Textract also writes its results into the bucket at <output_prefix>/<job_id>/1, /2, ...
    """

    kwargs = {
        "DocumentLocation": {"S3Object": {"Bucket": BUCKET_NAME, "Name": key}},
        "FeatureTypes": ["FORMS", "TABLES"],
    }
    if output_prefix:
        kwargs["OutputConfig"] = {"S3Bucket": BUCKET_NAME, "S3Prefix": output_prefix}

    return get_client("textract").start_document_analysis(**kwargs)["JobId"]


def get_analysis_status(job_id: str) -> str:
    """ current status of the job: IN_PROGRESS, SUCCEEDED, FAILED, or PARTIAL_SUCCESS """

    # we only care about the status here, so don't pull back a full page of blocks
    response = get_client("textract").get_document_analysis(JobId=job_id, MaxResults=1)

    return response["JobStatus"]


def get_blocks(job_id: str) -> list[dict]:
    """ page through every block of a finished job """

    textract = get_client("textract")

    blocks: list[dict] = []
    kwargs = {"JobId": job_id}
    while True:
        response = textract.get_document_analysis(**kwargs)
        blocks.extend(response["Blocks"])

        if "NextToken" not in response:
            return blocks
        kwargs["NextToken"] = response["NextToken"]


if __name__ == "__main__":
    import sys
    import time

    job_id = start_analysis(sys.argv[1])
    while (status := get_analysis_status(job_id)) == "IN_PROGRESS":
        time.sleep(5)

    print(f"{sys.argv[1]}: {status}, {len(get_blocks(job_id))} blocks")
