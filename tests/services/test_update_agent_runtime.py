"""Deploying the Runtime changes only its image, by digest, carries every other setting forward, and waits for READY."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "script" / "update_agent_runtime.py"
spec = importlib.util.spec_from_file_location("update_agent_runtime", SCRIPT)
update_agent_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_agent_runtime)

IMAGE = "397345411365.dkr.ecr.us-east-1.amazonaws.com/fieldsight-runtime@sha256:" + "a" * 64
CURRENT = {
    "agentRuntimeId": "fieldsight-abc123", "agentRuntimeArn": "arn:...", "agentRuntimeVersion": "3", "status": "READY",
    "roleArn": "arn:aws:iam::397345411365:role/FieldSightRuntimeExecution",
    "networkConfiguration": {"networkMode": "PUBLIC"},
    "environmentVariables": {"FIELDSIGHT_ENVIRONMENT": "prod"},
    "requestHeaderConfiguration": {"requestHeaderAllowlist": ["X-Amzn-Bedrock-AgentCore-Runtime-Custom-Thread"]},
    "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "old@sha256:" + "b" * 64}},
    "createdAt": "2026-09-20", "workloadIdentityDetails": {"workloadIdentityArn": "arn:..."},
}


class FakeClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.updates = []
        members = {"agentRuntimeId", "agentRuntimeArtifact", "roleArn", "networkConfiguration", "environmentVariables",
                   "requestHeaderConfiguration", "authorizerConfiguration", "description"}
        shape = SimpleNamespace(members={name: None for name in members})
        self.meta = SimpleNamespace(service_model=SimpleNamespace(operation_model=lambda name: SimpleNamespace(input_shape=shape)))

    def get_agent_runtime(self, agentRuntimeId):
        assert agentRuntimeId == "fieldsight-abc123"
        return CURRENT if not self.updates else {**CURRENT, "status": self.statuses.pop(0)}

    def update_agent_runtime(self, **request):
        self.updates.append(request)


def test_only_the_image_changes_and_every_setting_is_carried_forward():
    client = FakeClient(["UPDATING", "READY"])

    update_agent_runtime.deploy(client, "fieldsight-abc123", IMAGE, sleep=lambda seconds: None)

    [sent] = client.updates
    assert sent["agentRuntimeArtifact"] == {"containerConfiguration": {"containerUri": IMAGE}}
    for kept in ("roleArn", "networkConfiguration", "environmentVariables", "requestHeaderConfiguration"):
        assert sent[kept] == CURRENT[kept]
    # read-only fields from the GET are never sent back
    assert not {"status", "createdAt", "agentRuntimeArn", "workloadIdentityDetails"} & set(sent)


@pytest.mark.parametrize("image", [
    "397345411365.dkr.ecr.us-east-1.amazonaws.com/fieldsight-runtime:latest",
    "docker.io/library/python@sha256:" + "a" * 64,
])
def test_only_an_ecr_image_pinned_by_digest_is_deployed(image):
    client = FakeClient([])
    with pytest.raises(ValueError, match="Deploy by digest"):
        update_agent_runtime.deploy(client, "fieldsight-abc123", image)
    assert client.updates == []


def test_a_failed_or_stuck_update_is_reported():
    with pytest.raises(RuntimeError, match="update failed"):
        update_agent_runtime.deploy(FakeClient(["UPDATE_FAILED"]), "fieldsight-abc123", IMAGE, sleep=lambda s: None)
    with pytest.raises(TimeoutError):
        update_agent_runtime.deploy(FakeClient(["UPDATING"] * 10), "fieldsight-abc123", IMAGE,
                                    timeout_seconds=20, poll_seconds=10, sleep=lambda s: None)
