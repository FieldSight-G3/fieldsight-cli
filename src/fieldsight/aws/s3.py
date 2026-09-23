import uuid

from fieldsight.config import BUCKET_NAME
from fieldsight.aws.client import get_client


def pdf_key(name, *, corpus: bool = False) -> str:
    """S3 key for a PDF: packets go under pdfs/, corpus docs under corpus/."""
    folder = "corpus" if corpus else "pdfs"
    return f"{folder}/{name}.pdf"


def upload_pdf(file_path) -> str:
    """Upload a PDF document to S3 and return its new document id."""
    document_id = str(uuid.uuid4())
    get_client("s3").upload_file(str(file_path), BUCKET_NAME, pdf_key(document_id))
    return document_id


def list_keys(folder: str) -> list[str]:
    """List every key under a folder in the S3 bucket, e.g. list_keys("corpus")."""
    paginator = get_client("s3").get_paginator('list_objects_v2')
    keys = []
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"{folder}/"):
        for obj in page.get('Contents', []):
            keys.append(obj['Key'])
    return keys


if __name__ == "__main__":
    for key in list_keys("corpus"):
        print(key)