"""Run one turn on the deployed AgentCore Runtime as the current analyst, and print the outcome.

Run it with the analyst's assumed-role profile, e.g. AWS_PROFILE=fieldsight-analyst: the caller proof is
signed with those credentials and bound to this runtime session, and the Runtime resolves the analyst from it.
The proof is never printed.

    python script/invoke_runtime.py --runtime-id fieldsight_runtime-AX6swGECVj --incident-id <uuid>
    python script/invoke_runtime.py --runtime-id ... --incident-id <uuid> --command ask --question "why column H?"
"""

import argparse
import json
import uuid

import boto3
from botocore.config import Config

from fieldsight.security.iam_caller_proof import issue_proof

# a full analyze turn runs for minutes; never retry, since a retry would resend a proof that has since expired
INVOKE = Config(read_timeout=360, retries={"total_max_attempts": 1})


def invoke(runtime_arn: str, payload: dict, session_id: str, region: str) -> dict:
    """ one /invocations call; the proof is added here so it never leaves this function """

    session = boto3.Session(region_name=region)
    body = {**payload, "caller_proof": issue_proof(session_id, region, session.get_credentials())}
    response = session.client("bedrock-agentcore", config=INVOKE).invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=json.dumps(body).encode(),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["response"].read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--command", choices=["analyze", "ask"], default="analyze")
    parser.add_argument("--question")
    parser.add_argument("--session-id", help="reuse a session to continue it; AgentCore needs 33+ characters")
    args = parser.parse_args()

    session = boto3.Session()
    region = session.region_name
    if not region:
        parser.error("Configure an AWS region for this profile")
    account_id = session.client("sts").get_caller_identity()["Account"]
    runtime_arn = f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{args.runtime_id}"
    session_id = args.session_id or f"fieldsight-runtime-{uuid.uuid4()}"

    payload = {"command": args.command, "incident_id": args.incident_id}
    if args.question:
        payload["question"] = args.question
    outcome = invoke(runtime_arn, payload, session_id, region)

    print(f"session: {session_id}")
    if not outcome.get("ok"):
        print(f"denied: {outcome['error']['code']}: {outcome['error']['message']}")
        return
    result = outcome["result"]
    print(f"run record: {result.get('run_id')}  correlation: {result.get('correlation_id')}")
    if result.get("refusal"):
        print(f"refused: {result['refusal'].get('reason')}: {result['refusal'].get('message')}")
    escalation = result.get("escalation") or {}
    print(f"requires review: {escalation.get('requires_review')}")
    print(json.dumps(result, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
