"""Point the AgentCore Runtime at a new container image, keeping every other setting, and wait until it is READY.

UpdateAgentRuntime can reset optional settings it isn't sent, so this reads the runtime first and sends back
every field the update accepts (network, environment, authorizer, header allowlist, ...), changing only the
image. The image must be an ECR reference pinned by digest (repo@sha256:...), per the requirements' §15.
"""

from __future__ import annotations

import argparse
import re
import time
from typing import Any

import boto3

DIGEST_URI = re.compile(r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")
READ_ONLY = {"agentRuntimeArn", "agentRuntimeName", "agentRuntimeVersion", "createdAt", "lastUpdatedAt", "status",
             "failureReason", "workloadIdentityDetails"}


def update_request(current: dict[str, Any], container_uri: str, accepted: set[str]) -> dict[str, Any]:
    """ the current settings the update accepts, with only the image changed """

    if not DIGEST_URI.fullmatch(container_uri):
        raise ValueError(f"Deploy by digest: expected an ECR repo@sha256:... image, got {container_uri!r}")
    request = {key: value for key, value in current.items() if key in accepted and key not in READ_ONLY}
    request["agentRuntimeId"] = current["agentRuntimeId"]
    request["agentRuntimeArtifact"] = {"containerConfiguration": {"containerUri": container_uri}}
    return request


def deploy(client: Any, runtime_id: str, container_uri: str, *, timeout_seconds: float = 900, poll_seconds: float = 10,
           sleep: Any = time.sleep) -> dict[str, Any]:
    current = client.get_agent_runtime(agentRuntimeId=runtime_id)
    accepted = set(client.meta.service_model.operation_model("UpdateAgentRuntime").input_shape.members)
    client.update_agent_runtime(**update_request(current, container_uri, accepted))

    waited = 0.0
    while True:
        status = client.get_agent_runtime(agentRuntimeId=runtime_id)
        if status["status"] == "READY":
            return status
        if status["status"].endswith("FAILED"):
            raise RuntimeError(f"AgentCore Runtime update failed: {status.get('failureReason', status['status'])}")
        if waited >= timeout_seconds:
            raise TimeoutError(f"AgentCore Runtime still {status['status']} after {timeout_seconds:.0f}s")
        sleep(poll_seconds)
        waited += poll_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--image", required=True, help="ECR image pinned by digest: <registry>/<repo>@sha256:<digest>")
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    ready = deploy(boto3.client("bedrock-agentcore-control", region_name=args.region), args.runtime_id, args.image)
    print(f"AgentCore Runtime {args.runtime_id} is READY at version {ready.get('agentRuntimeVersion')} with {args.image}")


if __name__ == "__main__":
    main()
