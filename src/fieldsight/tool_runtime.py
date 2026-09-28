"""Start the tool API with verified IAM callers."""

import re

from flask import Flask

from fieldsight.config import settings
from fieldsight.iam_caller_proof import caller_resolver
from fieldsight.repository import AnalystRepository
from fieldsight.tool_api import create_app


def create_production_app() -> Flask:
    role_arns = {arn.strip() for arn in settings.analyst_role_arns.split(",") if arn.strip()}
    role_pattern = re.compile(r"arn:aws:iam::(\d{12}):role/[\w+=,.@-]{1,64}", re.ASCII)
    matches = [role_pattern.fullmatch(arn) for arn in role_arns]

    if not matches or any(match is None for match in matches):
        raise RuntimeError("Configure valid analyst IAM role ARNs")

    account_ids = {match.group(1) for match in matches if match is not None}
    if len(account_ids) != 1:
        raise RuntimeError("Analyst IAM roles must belong to one AWS account")

    repository = AnalystRepository()
    resolve_caller = caller_resolver(
        repository.email_for_iam_principal,
        settings.aws_region,
        next(iter(account_ids)),
        role_arns,
    )
    return create_app(caller_resolver=resolve_caller)