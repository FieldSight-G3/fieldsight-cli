"""Preview or create the two-tool AgentCore API Gateway stage target.

Run after the REST API stage, Gateway, and REQUEST interceptor exist. The
default is a read-only preview. --apply creates the target using AWS IAM.
"""

from __future__ import annotations

import argparse
import json
from typing import Any


def target_request(gateway_id: str, rest_api_id: str, stage: str, name: str = "FieldSightReadTools") -> dict[str, Any]:
    return {
        "gatewayIdentifier": gateway_id,
        "name": name,
        "targetConfiguration": {
            "mcp": {
                "apiGateway": {
                    "restApiId": rest_api_id,
                    "stage": stage,
                    "apiGatewayToolConfiguration": {
                        "toolFilters": [
                            {"filterPath": "/tools/get_incident_extraction", "methods": ["POST"]},
                            {"filterPath": "/tools/find_similar_incidents", "methods": ["POST"]},
                        ],
                        "toolOverrides": [
                            {
                                "path": "/tools/get_incident_extraction",
                                "method": "POST",
                                "name": "get_incident_extraction",
                                "description": "Read extracted facts for the caller's current incident session; no incident ID argument.",
                            },
                            {
                                "path": "/tools/find_similar_incidents",
                                "method": "POST",
                                "name": "find_similar_incidents",
                                "description": "Return up to five entitled, closed precedent incidents for the current session.",
                            },
                        ],
                    },
                }
            }
        },
        "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        "metadataConfiguration": {"allowedRequestHeaders": ["x-fieldsight-thread-id"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--rest-api-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--name", default="FieldSightReadTools")
    parser.add_argument("--region", required=True)
    parser.add_argument("--apply", action="store_true", help="Actually create the AWS Gateway target")
    args = parser.parse_args()
    request = target_request(args.gateway_id, args.rest_api_id, args.stage, args.name)
    if not args.apply:
        print(json.dumps(request, indent=2))
        return
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=args.region)
    result = client.create_gateway_target(**request)
    print(json.dumps({"gatewayTargetId": result.get("targetId"), "status": result.get("status")}, indent=2))


if __name__ == "__main__":
    main()
