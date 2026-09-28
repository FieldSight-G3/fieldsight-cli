"""Exercise identity proof validation without calling live AWS services."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from botocore.credentials import Credentials
from flask import Flask

from fieldsight.iam_caller_proof import caller_resolver, issue_proof, verify_proof
from fieldsight.tool_service import ToolDenied

REGION = "us-east-1"
ACCOUNT = "123456789012"
THREAD = "analyst-incident-recordability"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/FieldSightAnalystLogan"
ARN = f"arn:aws:sts::{ACCOUNT}:assumed-role/FieldSightAnalystLogan/logan-session"
STS_RESPONSE = (f"<GetCallerIdentityResponse><GetCallerIdentityResult><Arn>{ARN}</Arn><Account>{ACCOUNT}</Account><UserId>AROAEXAMPLE:logan-session</UserId></GetCallerIdentityResult></GetCallerIdentityResponse>").encode()


def replace_query(proof: str, key: str, value: str) -> str:
    parsed = urlsplit(proof)
    query = dict(parse_qsl(parsed.query))
    query[key] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


class CallerProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credentials = Credentials("ASIAEXAMPLE", "secret-example", "temporary-session-token")
        self.proof = issue_proof(THREAD, REGION, self.credentials)
        self.signed_at = datetime.strptime(dict(parse_qsl(urlsplit(self.proof).query))["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)

    def test_proof_is_short_lived_and_bound_to_session(self) -> None:
        query = dict(parse_qsl(urlsplit(self.proof).query))
        self.assertEqual(query["X-Amz-Expires"], "60")
        self.assertEqual(query["X-Amz-SignedHeaders"], "host;x-fieldsight-thread-id")
        seen = []

        def fetch(request):
            seen.append(request.get_header("X-fieldsight-thread-id"))
            return STS_RESPONSE

        self.assertEqual(verify_proof(self.proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=fetch, now=self.signed_at), ROLE_ARN)
        self.assertEqual(seen, [THREAD])

    def test_standard_multiword_region_is_supported(self) -> None:
        self.assertIn("sts.ap-southeast-2.amazonaws.com", issue_proof(THREAD, "ap-southeast-2", self.credentials))

    def test_bad_destinations_actions_and_expired_proofs_never_reach_sts(self) -> None:
        proofs = (
            self.proof.replace(f"sts.{REGION}.amazonaws.com", "evil.example"),
            replace_query(self.proof, "Action", "AssumeRole"),
            replace_query(self.proof, "X-Amz-SignedHeaders", "host"),
            replace_query(self.proof, "X-Amz-Expires", "3600"),
            self.proof + "&Action=AssumeRole",
        )

        def no_fetch(request):
            self.fail("Malformed caller proof reached STS")

        for index, proof in enumerate(proofs):
            with self.subTest(index=index), self.assertRaises(ToolDenied):
                verify_proof(proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=no_fetch, now=self.signed_at)
        with self.assertRaises(ToolDenied):
            verify_proof(self.proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=no_fetch, now=self.signed_at.replace(year=2027))

    def test_only_an_enrolled_analyst_role_can_be_verified(self) -> None:
        with self.assertRaises(ToolDenied):
            verify_proof(self.proof, THREAD, REGION, "999999999999", {ROLE_ARN}, fetch=lambda request: STS_RESPONSE, now=self.signed_at)
        role_xml = STS_RESPONSE.replace(b"FieldSightAnalystLogan", b"FieldSightAgentCoreRuntimeRole")
        with self.assertRaises(ToolDenied):
            verify_proof(self.proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=lambda request: role_xml, now=self.signed_at)
        user_xml = STS_RESPONSE.replace(ARN.encode(), f"arn:aws:iam::{ACCOUNT}:user/fieldsight-d".encode())
        with self.assertRaises(ToolDenied):
            verify_proof(self.proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=lambda request: user_xml, now=self.signed_at)
        with self.assertRaises(ToolDenied):
            verify_proof(self.proof, THREAD, REGION, ACCOUNT, set(), fetch=lambda request: STS_RESPONSE, now=self.signed_at)

    def test_role_identity_is_stable_across_sessions(self) -> None:
        other_session = STS_RESPONSE.replace(b"logan-session", b"new-session")
        self.assertEqual(verify_proof(self.proof, THREAD, REGION, ACCOUNT, {ROLE_ARN}, fetch=lambda request: other_session, now=self.signed_at), ROLE_ARN)

    def test_long_lived_iam_user_credentials_cannot_issue_proof(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Temporary IAM role credentials"):
            issue_proof(THREAD, REGION, Credentials("AKIAEXAMPLE", "secret-example"))

    def test_resolver_looks_up_verified_arn_only(self) -> None:
        app = Flask(__name__)
        lookups = []

        def lookup(arn: str) -> str | None:
            lookups.append(arn)
            return "logan@example.invalid" if arn == ROLE_ARN else None

        resolver = caller_resolver(lookup, REGION, ACCOUNT, {ROLE_ARN})
        with app.test_request_context(headers={"X-Fieldsight-Thread-Id": THREAD, "X-Fieldsight-Caller-Proof": self.proof, "X-Fieldsight-Email": "forged@example.invalid"}), patch("fieldsight.iam_caller_proof.verify_proof", return_value=ROLE_ARN):
            self.assertEqual(resolver(), "logan@example.invalid")
        self.assertEqual(lookups, [ROLE_ARN])


if __name__ == "__main__":
    unittest.main()
