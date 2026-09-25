""" the corpus Knowledge Base: write chunks where its S3 data source reads them, and sync it """

import json

from ..config import settings
from . import clients
from .s3 import put_text


def write_chunk(folder: str, chunk_id: str, text: str, metadata: dict) -> None:
    """ one chunk as the KB's S3 data source expects it: the text, and its .metadata.json beside it """

    key = f"{folder}/{chunk_id}.txt"
    put_text(key, text)
    put_text(f"{key}.metadata.json", json.dumps({"metadataAttributes": metadata}))


def start_sync() -> str:
    """ start an ingestion job over the data source, returns the job id """

    job = clients.bedrock_agent().start_ingestion_job(
        knowledgeBaseId=settings.bedrock_kb_id, 
        dataSourceId=settings.bedrock_kb_data_source_id
        )
    return job["ingestionJob"]["ingestionJobId"]


def get_sync(job_id: str) -> dict:
    """ the job's status, statistics and failure reasons """

    return clients.bedrock_agent().get_ingestion_job(
        knowledgeBaseId=settings.bedrock_kb_id, 
        dataSourceId=settings.bedrock_kb_data_source_id, 
        ingestionJobId=job_id,
    )["ingestionJob"]
