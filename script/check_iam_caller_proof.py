"""Verify a live analyst IAM role proof without printing the signed URL."""

from __future__ import annotations

import argparse

import boto3

from fieldsight.iam_caller_proof import issue_proof, verify_proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-arn", required=True, help="Exact analyst IAM role ARN assigned to your profile")
    args = parser.parse_args()
    session = boto3.Session()
    region = session.region_name
    if not region:
        parser.error("Configure the AWS region for your assumed-role profile")
    identity = session.client("sts").get_caller_identity()
    account_id = identity["Account"]
    role_prefix = f"arn:aws:iam::{account_id}:role/"
    if not args.role_arn.startswith(role_prefix):
        parser.error("The analyst role must be in the signed-in AWS account")
    role_name = args.role_arn[len(role_prefix):]
    if not role_name or "/" in role_name or not identity["Arn"].startswith(f"arn:aws:sts::{account_id}:assumed-role/{role_name}/"):
        parser.error("AWS_PROFILE must select the matching assumed analyst role, not an IAM user")
    thread_id = "fieldsight-proof-smoke-test"
    proof = issue_proof(thread_id, region, session.get_credentials())
    verified_role = verify_proof(proof, thread_id, region, account_id, {args.role_arn})
    if verified_role != args.role_arn:
        raise RuntimeError("STS returned the wrong analyst role")
    print("PASS: IAM analyst role caller proof verified")


if __name__ == "__main__":
    main()
