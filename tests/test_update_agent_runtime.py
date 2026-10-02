"""update_agent_runtime sends back every setting the update accepts, changing only the image and the named variables."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "script" / "update_agent_runtime.py"
spec = importlib.util.spec_from_file_location("update_agent_runtime", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/fieldsight@sha256:" + "a" * 64
CURRENT = {
    "agentRuntimeId": "rt-1", "agentRuntimeArn": "arn:rt-1", "status": "READY",
    "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "old@sha256:" + "b" * 64}},
    "roleArn": "arn:role", "networkConfiguration": {"networkMode": "VPC"},
    "environmentVariables": {"FIELDSIGHT_DATABASE_URL": "kept", "FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD": "0.46"},
}
ACCEPTED = {"agentRuntimeId", "agentRuntimeArtifact", "roleArn", "networkConfiguration", "environmentVariables"}


def test_named_variables_merge_into_the_current_environment_and_the_image_stays():
    request = script.update_request(CURRENT, None, ACCEPTED, {"FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD": "0.483"})

    assert request["environmentVariables"] == {"FIELDSIGHT_DATABASE_URL": "kept", "FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD": "0.483"}
    assert request["agentRuntimeArtifact"] == CURRENT["agentRuntimeArtifact"]
    assert request["roleArn"] == "arn:role" and "status" not in request and "agentRuntimeArn" not in request


def test_an_image_alone_leaves_the_environment_as_it_is():
    request = script.update_request(CURRENT, IMAGE, ACCEPTED)

    assert request["agentRuntimeArtifact"] == {"containerConfiguration": {"containerUri": IMAGE}}
    assert request["environmentVariables"] == CURRENT["environmentVariables"]


def test_an_image_not_pinned_by_digest_is_refused():
    with pytest.raises(ValueError):
        script.update_request(CURRENT, "fieldsight:latest", ACCEPTED)
