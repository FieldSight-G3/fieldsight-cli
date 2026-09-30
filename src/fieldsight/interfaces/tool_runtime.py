"""Start the tool API with verified IAM callers."""

from flask import Flask

from fieldsight.config import settings
from fieldsight.interfaces.tool_api import create_app
from fieldsight.logging_context import configure_logging
from fieldsight.repository import AnalystRepository
from fieldsight.security.iam_caller_proof import (
    caller_resolver,
    enrolled_analyst_roles,
)


def create_production_app() -> Flask:
    configure_logging()
    role_arns, account_id = enrolled_analyst_roles(settings.analyst_role_arns)
    repository = AnalystRepository()
    resolve_caller = caller_resolver(repository.email_for_iam_principal, settings.aws_region, account_id, role_arns)
    return create_app(caller_resolver=resolve_caller)