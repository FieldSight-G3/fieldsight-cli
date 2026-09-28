"""Flask API for the two read-only ECS tool endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flask import Flask, jsonify, request
from pydantic import ValidationError
from sqlalchemy import text as sql_text

from fieldsight.errors import FailureCode, ToolDenied
from fieldsight.interfaces.tool_service import ToolFailure, ToolResponse, ToolService

logger = logging.getLogger(__name__)


def create_app(service: ToolService | None = None, engine: Any = None, caller_resolver: Callable[[], str] | None = None) -> Flask:
    app = Flask(__name__)
    if service is None:
        from fieldsight.tool_store import GatewayReadStore

        store = GatewayReadStore()
        service = ToolService(store)
        engine = store.engine
    if caller_resolver is None:
        caller_resolver = _unconfigured_caller

    @app.get("/health/live")
    def live() -> Any:
        return jsonify({"status": "alive"})

    @app.get("/health/ready")
    def ready() -> Any:
        if engine is None:
            return jsonify({"status": "unavailable"}), 503
        try:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1"))
        except Exception:
            logger.exception("readiness check failed")
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ready"})

    def run_tool(tool: str) -> Any:
        thread_id = request.headers.get("X-Fieldsight-Thread-Id", "")
        if not thread_id.strip():
            return _failure("unauthenticated", "A bound session is required", 401)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _failure("invalid_input", "A JSON object is required", 400)
        try:
            assert service is not None
            assert caller_resolver is not None
            verified_email = caller_resolver()
            if not verified_email:
                raise ToolDenied("unauthenticated", "Verified caller is required")
            result = (
                service.get_incident_extraction(verified_email, thread_id, payload)
                if tool == "get_incident_extraction"
                else service.find_similar_incidents(verified_email, thread_id, payload)
            )
        except ValidationError:
            return _failure("invalid_input", "Invalid tool arguments", 400)
        except ToolDenied as error:
            status = {"unauthenticated": 401, "not_entitled": 403, "not_found": 404,
                      "insufficient_data": 422, "unavailable": 503, "invalid_input": 400}[error.code]
            return _failure(error.code, str(error), status)
        except Exception:
            logger.exception("tool failed: %s", tool)
            return _failure("unavailable", "Tool service unavailable", 503)
        logger.info("gateway tool invoked: %s", tool)
        return jsonify(result.model_dump(mode="json"))

    @app.post("/tools/get_incident_extraction")
    def extraction() -> Any:
        return run_tool("get_incident_extraction")

    @app.post("/tools/find_similar_incidents")
    def similar() -> Any:
        return run_tool("find_similar_incidents")

    return app


def _failure(code: FailureCode, message: str, status: int) -> Any:
    return jsonify(ToolResponse(ok=False, error=ToolFailure(code=code, message=message)).model_dump(mode="json")), status


def _unconfigured_caller() -> str:
    """Deny until a verified Gateway caller binding is implemented."""
    raise ToolDenied("unauthenticated", "Verified caller is required")
