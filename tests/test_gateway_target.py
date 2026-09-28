"""Protect the publicly exposed tool list and the Pydantic-generated contract."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "script" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GatewayTargetTests(unittest.TestCase):
    def test_gateway_uses_iam_without_jwt_interceptor(self) -> None:
        request = load_script("configure_gateway_iam").gateway_request("role")
        self.assertEqual(request["authorizerType"], "AWS_IAM")
        self.assertNotIn("authorizerConfiguration", request)
        self.assertNotIn("interceptorConfigurations", request)

    def test_only_two_read_routes_are_advertised(self) -> None:
        request = load_script("configure_gateway_target").target_request("gateway", "api", "prod")
        target = request["targetConfiguration"]["mcp"]["apiGateway"]["apiGatewayToolConfiguration"]
        self.assertEqual({(item["filterPath"], tuple(item["methods"])) for item in target["toolFilters"]}, {
            ("/tools/get_incident_extraction", ("POST",)),
            ("/tools/find_similar_incidents", ("POST",)),
        })
        self.assertEqual(request["metadataConfiguration"]["allowedRequestHeaders"], ["x-fieldsight-thread-id", "x-fieldsight-caller-proof"])
        self.assertEqual(request["credentialProviderConfigurations"], [{"credentialProviderType": "GATEWAY_IAM_ROLE"}])

    def test_pydantic_schema_never_exposes_subject_or_caller(self) -> None:
        spec = load_script("generate_tool_openapi").specification()
        self.assertEqual(set(spec["paths"]), {"/tools/get_incident_extraction", "/tools/find_similar_incidents"})
        for path in spec["paths"].values():
            body = path["post"]["requestBody"]["content"]["application/json"]["schema"]
            self.assertNotIn("incident_id", body.get("properties", {}))
            self.assertNotIn("analyst_id", body.get("properties", {}))
            self.assertEqual(body["additionalProperties"], False)

    def test_private_integration_keeps_iam_on_both_methods(self) -> None:
        spec = load_script("generate_tool_openapi").specification("vpc123", "arn:aws:elasticloadbalancing:region:123:loadbalancer/app/example/123", "http://internal-alb")
        for path, methods in spec["paths"].items():
            method = methods["post"]
            self.assertEqual(method["x-amazon-apigateway-auth"], {"type": "AWS_IAM"})
            integration = method["x-amazon-apigateway-integration"]
            self.assertEqual(integration["connectionType"], "VPC_LINK")
            self.assertEqual(integration["uri"], "http://internal-alb" + path)


if __name__ == "__main__":
    unittest.main()
