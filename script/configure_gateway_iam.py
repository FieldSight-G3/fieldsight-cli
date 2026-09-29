"""Preview or create a FieldSight IAM-authenticated AgentCore MCP Gateway."""

import argparse
import json
from typing import Any


def gateway_request(role_arn: str, name: str = "FieldSightTools") -> dict[str, Any]:
    return {"name": name, "roleArn": role_arn, "protocolType": "MCP", "authorizerType": "AWS_IAM"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-role-arn", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--name", default="FieldSightTools")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    request = gateway_request(args.gateway_role_arn, args.name)
    if not args.apply:
        print(json.dumps(request, indent=2))
        return
    import boto3

    result = boto3.client("bedrock-agentcore-control", region_name=args.region).create_gateway(**request)
    print(json.dumps({key: result.get(key) for key in ("gatewayId", "gatewayUrl", "status")}, indent=2))


if __name__ == "__main__":
    main()
