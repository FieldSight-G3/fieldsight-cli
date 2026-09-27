"""Short-lived, session-bound AWS IAM identity proof for Gateway read tools.

The analyst's Identity Center credentials sign an STS GetCallerIdentity request.
ECS sends that request to STS to authenticate its signer. The proof is a bearer
secret until it expires; pass it only through TLS and never write it to logs.
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import boto3
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from fieldsight.tool_service import ToolDenied

PROOF_HEADER = "X-Fieldsight-Caller-Proof"
THREAD_HEADER = "X-Fieldsight-Thread-Id"
_REGION = re.compile(r"[a-z]{2}-(?:[a-z]+-)*[a-z]+-\d+\Z")
_ACCOUNT = re.compile(r"\d{12}\Z")
_QUERY_KEYS = frozenset({
    "Action", "Version", "X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date",
    "X-Amz-Expires", "X-Amz-Security-Token", "X-Amz-Signature", "X-Amz-SignedHeaders",
})


def issue_proof(thread_id: str, region: str, credentials: Any = None) -> str:
    """Sign a proof with the *analyst's* current Identity Center credentials."""
    _check_thread(thread_id)
    host = _sts_host(region)
    credentials = credentials or boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("Sign in with AWS IAM Identity Center before calling the Gateway")
    frozen = credentials.get_frozen_credentials()
    if not frozen.token:
        raise RuntimeError("Temporary Identity Center credentials are required")
    request = AWSRequest(
        method="GET",
        url=f"https://{host}/?Action=GetCallerIdentity&Version=2011-06-15",
        headers={THREAD_HEADER: thread_id},
    )
    SigV4QueryAuth(frozen, "sts", region, expires=60).add_auth(request)
    return request.url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _fetch_sts(request: urllib.request.Request) -> bytes:
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=3) as response:
        if response.status != 200:
            raise ValueError("STS rejected the caller proof")
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError("STS response is too large")
    return payload


def verify_proof(proof: str, thread_id: str, region: str, account_id: str, *, fetch: Callable[[urllib.request.Request], bytes] = _fetch_sts, now: datetime | None = None) -> str:
    """Return the STS-verified Identity Center principal ARN, or deny the call."""
    try:
        _check_thread(thread_id)
        host = _sts_host(region)
        if not _ACCOUNT.fullmatch(account_id) or not isinstance(proof, str) or len(proof) > 4096:
            raise ValueError("Invalid caller proof configuration")
        parsed = urlsplit(proof)
        if parsed.scheme != "https" or parsed.netloc != host or parsed.path != "/" or parsed.fragment:
            raise ValueError("Invalid STS destination")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        if len(pairs) != len(query) or set(query) != _QUERY_KEYS:
            raise ValueError("Unexpected STS query")
        if query["Action"] != "GetCallerIdentity" or query["Version"] != "2011-06-15":
            raise ValueError("Unexpected STS action")
        if query["X-Amz-Algorithm"] != "AWS4-HMAC-SHA256" or query["X-Amz-SignedHeaders"] != "host;x-fieldsight-thread-id":
            raise ValueError("Caller proof is not bound to the thread")
        credential = query["X-Amz-Credential"].split("/")
        if len(credential) != 5 or not credential[0].startswith("ASIA") or credential[2:] != [region, "sts", "aws4_request"]:
            raise ValueError("Temporary STS credentials are required")
        signed_at = datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if credential[1] != signed_at.strftime("%Y%m%d") or query["X-Amz-Expires"] != "60":
            raise ValueError("Invalid proof lifetime")
        age = ((now or datetime.now(UTC)) - signed_at).total_seconds()
        if age < -30 or age > 60 or not re.fullmatch(r"[a-fA-F0-9]{64}", query["X-Amz-Signature"]):
            raise ValueError("Caller proof expired")
        if not query["X-Amz-Security-Token"]:
            raise ValueError("Session token is required")
        request = urllib.request.Request(proof, headers={THREAD_HEADER: thread_id}, method="GET")
        root = ET.fromstring(fetch(request))
        arn = root.findtext(".//{*}Arn")
        account = root.findtext(".//{*}Account")
        user_id = root.findtext(".//{*}UserId")
        if account != account_id or not user_id or not arn or not arn.startswith(f"arn:aws:sts::{account_id}:assumed-role/AWSReservedSSO_"):
            raise ValueError("Caller is not an enrolled Identity Center principal")
        return arn
    except (ValueError, TypeError, OverflowError, OSError, ET.ParseError) as exc:
        raise ToolDenied("unauthenticated", "Valid Identity Center caller proof is required") from exc


def caller_resolver(lookup_email: Callable[[str], str | None], region: str, account_id: str) -> Callable[[], str]:
    """Build the Flask resolver; Jenya's repository supplies the exact ARN lookup."""
    from flask import request

    def resolve() -> str:
        principal_arn = verify_proof(request.headers.get(PROOF_HEADER, ""), request.headers.get(THREAD_HEADER, ""), region, account_id)
        email = lookup_email(principal_arn)
        if not email:
            raise ToolDenied("not_entitled", "Caller has no enrolled analyst record")
        return email

    return resolve


def _check_thread(thread_id: str) -> None:
    if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 200 or not thread_id.isascii() or any(char.isspace() for char in thread_id):
        raise ValueError("A nonempty dispatcher-bound thread ID is required")


def _sts_host(region: str) -> str:
    if not isinstance(region, str) or not _REGION.fullmatch(region):
        raise ValueError("Use a commercial AWS region, for example us-east-1")
    return f"sts.{region}.amazonaws.com"
