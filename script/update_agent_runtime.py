"""Point the AgentCore Runtime at a new container image, or change some of its environment variables, keeping every
other setting, and wait until it is READY.

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


def update_request(current: dict[str, Any], container_uri: str | None, accepted: set[str],
                   env: dict[str, str] | None = None) -> dict[str, Any]:
    """ the current settings the update accepts, with only the image (when given) and the named variables changed

        The environment map is replaced whole by the update, so the named variables are merged into the current one.
    """

    if container_uri is not None and not DIGEST_URI.fullmatch(container_uri):
        raise ValueError(f"Deploy by digest: expected an ECR repo@sha256:... image, got {container_uri!r}")
    request = {key: value for key, value in current.items() if key in accepted and key not in READ_ONLY}
    request["agentRuntimeId"] = current["agentRuntimeId"]
    if container_uri is not None:
        request["agentRuntimeArtifact"] = {"containerConfiguration": {"containerUri": container_uri}}
    if env:
        request["environmentVariables"] = {**(current.get("environmentVariables") or {}), **env}
    return request


def deploy(client: Any, runtime_id: str, container_uri: str | None, *, env: dict[str, str] | None = None,
           timeout_seconds: float = 900, poll_seconds: float = 10, sleep: Any = time.sleep) -> dict[str, Any]:
    current = client.get_agent_runtime(agentRuntimeId=runtime_id)
    accepted = set(client.meta.service_model.operation_model("UpdateAgentRuntime").input_shape.members)
    client.update_agent_runtime(**update_request(current, container_uri, accepted, env))

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
    parser.add_argument("--image", help="ECR image pinned by digest: <registry>/<repo>@sha256:<digest>; omit to keep the current one")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE",
                        help="set one environment variable, keeping the others; repeat for more")
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    if not args.image and not args.env:
        parser.error("give --image, --env, or both")
    env = dict(pair.split("=", 1) for pair in args.env)
    ready = deploy(boto3.client("bedrock-agentcore-control", region_name=args.region), args.runtime_id, args.image, env=env)
    # names only: a value can be a secret
    print(f"AgentCore Runtime {args.runtime_id} is READY at version {ready.get('agentRuntimeVersion')}"
          + (f" with {args.image}" if args.image else "") + (f"; set {', '.join(env)}" if env else ""))


if __name__ == "__main__":
    main()
