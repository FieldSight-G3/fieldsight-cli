""" the CLI's remote mode: analyze and ask run on the deployed AgentCore Runtime instead of in this process

    Set FIELDSIGHT_RUNTIME_ID to the runtime's id and the CLI sends each turn there, as the analyst whose assumed role
    this AWS profile holds. The caller proof is signed here and bound to the runtime session; the Runtime resolves the
    analyst from it, so the identity never comes from a request field. The proof is never printed or stored.
"""

import json
import os
import uuid
from typing import Any

import boto3
from botocore.config import Config

from ..security.iam_caller_proof import issue_proof
from ..types.run import TurnRun

RUNTIME_ID = "FIELDSIGHT_RUNTIME_ID"
# a full analyze turn runs for minutes; never retry, since a retry would resend a proof that has since expired
INVOKE = Config(read_timeout=360, retries={"total_max_attempts": 1})
# fixed so the same analyst and incident always land on the same runtime session
SESSION_NAMESPACE = uuid.UUID("6f1c2a52-3c1e-4b8e-9a51-7d0c4f4e2b19")


class RemoteDenied(Exception):
    """ the Runtime refused the turn with a structured error """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def runtime_id() -> str | None:
    return os.environ.get(RUNTIME_ID) or None


def session_for(caller_arn: str, incident_id: str) -> str:
    """ one runtime session per (AWS caller, incident), so ask continues what analyze started; AgentCore needs 33+ characters """

    return f"fieldsight-{uuid.uuid5(SESSION_NAMESPACE, f'{caller_arn}|{incident_id}')}"


def turn(request: dict[str, Any], runtime: str) -> TurnRun:
    """ one turn on the deployed Runtime, returned as the TurnRun a local turn would have produced """

    session = boto3.Session()
    region = session.region_name
    if not region:
        raise RuntimeError("Configure an AWS region for this profile")
    identity = session.client("sts").get_caller_identity()
    runtime_arn = f"arn:aws:bedrock-agentcore:{region}:{identity['Account']}:runtime/{runtime}"
    session_id = session_for(identity["Arn"], str(request.get("incident_id")))

    body = {**request, "caller_proof": issue_proof(session_id, region, session.get_credentials())}
    response = session.client("bedrock-agentcore", config=INVOKE).invoke_agent_runtime(
        agentRuntimeArn=runtime_arn, runtimeSessionId=session_id, payload=json.dumps(body).encode(),
        contentType="application/json", accept="application/json")
    outcome = json.loads(response["response"].read())
    if not outcome.get("ok"):
        raise RemoteDenied(outcome["error"]["code"], outcome["error"]["message"])
    return TurnRun.model_validate(outcome["result"])
