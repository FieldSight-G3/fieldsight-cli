""" where packet artifacts sit in S3 """

import hashlib
from pathlib import Path

from ...aws.s3 import upload
from ...types.artifacts import STORED_ARTIFACT, StoredArtifact


def artifact_key(path: Path, digest: str) -> str:
    """ S3 key by content hash, so re-ingesting a file hits the same object """

    return f"packets/{digest}/{path.name}"


def upload_artifact(file_path) -> StoredArtifact:
    """ upload a packet artifact (PDF or image), keyed by content hash """

    path = Path(file_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = STORED_ARTIFACT.validate_python({"name": path.name, "digest": digest, "key": artifact_key(path, digest)})
    upload(path, artifact["key"])
    return artifact
