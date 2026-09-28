"""Generate the tool HTTP contract from the Pydantic models used by ECS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fieldsight.tool_service import (
    GetExtractionInput,
    SimilarIncidentsInput,
    ToolResponse,
)


def specification(vpc_link_id: str | None = None, alb_arn: str | None = None, alb_url: str | None = None) -> dict[str, Any]:
    if any(value is not None for value in (vpc_link_id, alb_arn, alb_url)) and not all(value for value in (vpc_link_id, alb_arn, alb_url)):
        raise ValueError("VPC link ID, ALB ARN, and internal ALB URL must be provided together")

    def operation(name: str, description: str, request_schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "operationId": name,
            "summary": description,
            "security": [{"sigv4Reference": []}],
            "x-amazon-apigateway-auth": {"type": "AWS_IAM"},
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": request_schema}},
            },
            "responses": {
                "200": {"description": "Successful read", "content": {"application/json": {"schema": ToolResponse.model_json_schema()}}},
                "400": {"description": "Structured validation error"},
                "401": {"description": "Unauthenticated caller"},
                "403": {"description": "Caller has no grant"},
                "503": {"description": "Structured unavailable error"},
            },
        }

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "FieldSight Gateway read tools", "version": "1.0.0"},
        "components": {"securitySchemes": {"sigv4Reference": {
            "type": "apiKey", "name": "Authorization", "in": "header", "x-amazon-apigateway-authtype": "awsSigv4"
        }}},
        "paths": {
            "/tools/get_incident_extraction": {
                "post": operation("get_incident_extraction", "Read the current incident's extracted facts", GetExtractionInput.model_json_schema())
            },
            "/tools/find_similar_incidents": {
                "post": operation("find_similar_incidents", "Find closed precedent cases for the current incident", SimilarIncidentsInput.model_json_schema())
            },
        },
    }
    if vpc_link_id and alb_arn and alb_url:
        for path, methods in spec["paths"].items():
            methods["post"]["x-amazon-apigateway-integration"] = {
                "type": "http_proxy",
                "httpMethod": "POST",
                "connectionType": "VPC_LINK",
                "connectionId": vpc_link_id,
                "integration-target": alb_arn,
                "uri": alb_url.rstrip("/") + path,
            }
    return spec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vpc-link-id", help="REST API VPC link V2 ID")
    parser.add_argument("--alb-arn", help="Internal ALB ARN")
    parser.add_argument("--alb-url", help="Internal ALB origin, such as http://internal-fieldsight-123.region.elb.amazonaws.com")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(specification(args.vpc_link_id, args.alb_arn, args.alb_url), indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
