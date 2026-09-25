""" run Textract over PDFs in S3 via the async API, which multi-page PDFs require """

from ..errors import ExtractionError
from . import clients
from .errors import raises
from .s3 import BUCKET_NAME, list_objects, read_json


@raises(ExtractionError, "Textract couldn't start the job")
def start_analysis(
    key: str, 
    output_prefix: str | None = None, 
    *, 
    features: list[str] | None = None, 
    token: str | None = None
    ) -> str:
    
    """ start an async Textract job on a PDF in S3; returns the job id. output_prefix also saves results to S3 """

    kwargs = {
        "DocumentLocation": {"S3Object": {"Bucket": BUCKET_NAME, "Name": key}},
        "FeatureTypes": features or ["FORMS", "TABLES"],
    }
    if token:
        kwargs["ClientRequestToken"] = token[:64]
    if output_prefix:
        kwargs["OutputConfig"] = {"S3Bucket": BUCKET_NAME, "S3Prefix": output_prefix}

    return clients.textract().start_document_analysis(**kwargs)["JobId"]


def get_analysis_status(job_id: str) -> str:
    """ current status of the job: IN_PROGRESS, SUCCEEDED, FAILED, or PARTIAL_SUCCESS """

    # only the status is needed, so skip fetching a page of blocks
    response = clients.textract().get_document_analysis(JobId=job_id, MaxResults=1)

    return response["JobStatus"]


def get_blocks(job_id: str) -> list[dict]:
    """ page through every block of a finished job """

    textract = clients.textract()

    blocks: list[dict] = []
    kwargs = {"JobId": job_id}
    while True:
        response = textract.get_document_analysis(**kwargs)
        blocks.extend(response["Blocks"])

        if "NextToken" not in response:
            return blocks
        kwargs["NextToken"] = response["NextToken"]


def load_output(prefix: str) -> list[dict]:
    """ blocks saved under output_prefix (e.g. textract/<doc_id>), from the newest run """

    # keep only numbered result parts, skipping .s3_access_check
    parts = [obj for obj in list_objects(prefix) if obj["Key"].rsplit("/", 1)[-1].isdigit()]
    if not parts:
        raise ExtractionError(f"no Textract output under {prefix}/")

    newest_job = max(
        parts, 
        key=lambda obj: obj["LastModified"]
        )["Key"].split("/")[-2]
    
    keys = sorted((
        obj["Key"] for obj in parts if obj["Key"].split("/")[-2] == newest_job), 
        key=lambda key: int(key.rsplit("/", 1)[-1])
        )
    return [block for key in keys for block in read_json(key)["Blocks"]]
