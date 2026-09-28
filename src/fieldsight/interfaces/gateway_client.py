"""Connect an AgentCore Runtime agent to an IAM-protected MCP Gateway."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class SigV4HttpxAuth(httpx.Auth):
    """Sign each request with current role credentials, including the MCP body."""

    requires_request_body = True

    def __init__(self, region: str) -> None:
        self.region = region
        self.credentials = boto3.Session().get_credentials()
        if self.credentials is None:
            raise RuntimeError("AWS credentials are required to call the AgentCore Gateway")

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        # Read fresh credentials for each request so a long-running agent can rotate its role credentials.
        credentials = self.credentials.get_frozen_credentials()
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in {"authorization", "connection", "host", "content-length", "x-amz-date", "x-amz-security-token"}
        }
        signed = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=headers)
        SigV4Auth(credentials, "bedrock-agentcore", self.region).add_auth(signed)
        for key, value in signed.headers.items():
            request.headers[key] = value
        yield request


def gateway_url(region: str) -> str:
    """Find the specific Gateway assigned to FieldSight, never an unrelated one."""
    url = os.environ.get("FIELDSIGHT_GATEWAY_URL") or os.environ.get("AGENTCORE_GATEWAY_FIELDSIGHTTOOLS_URL")
    if not url:
        raise RuntimeError("Set FIELDSIGHT_GATEWAY_URL to the FieldSight HTTPS MCP Gateway URL")

    parsed = urlsplit(url)
    suffix = f".gateway.bedrock-agentcore.{region}.amazonaws.com"
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(suffix) or parsed.username or parsed.password or parsed.port or parsed.path != "/mcp":
        raise RuntimeError("Set FIELDSIGHT_GATEWAY_URL to the FieldSight HTTPS MCP Gateway URL")
    return url


@asynccontextmanager
async def gateway_tools(thread_id: str, *, caller_proof: str, region: str | None = None) -> AsyncIterator[list[Any]]:
    """Expose Gateway tools with a caller proof supplied by the trusted dispatcher."""
    if not thread_id.strip():
        raise ValueError("A dispatcher-bound thread ID is required")
    if not caller_proof:
        raise ValueError("A signed analyst IAM role proof is required")
    aws_region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not aws_region:
        raise RuntimeError("Set AWS_REGION for SigV4 signing")
    async with (
        httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=False,
            auth=SigV4HttpxAuth(aws_region),
            headers={"x-fieldsight-thread-id": thread_id, "x-fieldsight-caller-proof": caller_proof},
        ) as client,
        streamable_http_client(gateway_url(aws_region), http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield await load_mcp_tools(session)
