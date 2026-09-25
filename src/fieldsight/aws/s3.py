""" reads and writes on the project bucket """

import json

from fieldsight.aws import clients
from fieldsight.config import settings

BUCKET_NAME = settings.packet_bucket


def upload(file_path, key: str) -> None:
    """ upload a local file to a fixed key """

    clients.s3().upload_file(str(file_path), BUCKET_NAME, key)


def put_text(key: str, text: str) -> None:
    """ write a UTF-8 text object """

    clients.s3().put_object(
        Bucket=BUCKET_NAME, 
        Key=key, 
        Body=text.encode("utf-8"), 
        ContentType="text/plain"
        )


def list_objects(folder: str) -> list[dict]:
    """ every object under a folder, with its Key and LastModified """

    paginator = clients.s3().get_paginator("list_objects_v2")
    return [obj for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"{folder}/") for obj in page.get("Contents", [])]


def list_keys(folder: str) -> list[str]:
    """ every key under a folder """

    return [obj["Key"] for obj in list_objects(folder)]


def read_json(key: str) -> dict:
    """ a JSON object's contents """

    return json.loads(clients.s3().get_object(Bucket=BUCKET_NAME, Key=key)["Body"].read())


def delete_folder(folder: str) -> None:
    """ delete every object under a folder, e.g. one doc's old chunk files """

    keys = list_keys(folder)
    for start in range(0, len(keys), 1000):     # delete_objects takes at most 1000 keys
        clients.s3().delete_objects(Bucket=BUCKET_NAME, Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]]})
