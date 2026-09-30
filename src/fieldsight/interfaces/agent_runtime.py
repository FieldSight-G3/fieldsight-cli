""" the AgentCore Runtime entrypoint: one turn per invocation, as the analyst the caller proof names

    The invoker (the CLI or another host) sends {"command": ..., "incident_id": ..., "question": ...,
    "caller_proof": ...}. The proof is the same 60-second STS GetCallerIdentity proof the Gateway path uses,
    signed by the analyst's own assumed role and bound to this runtime session, so the identity never comes
    from a request field the model or the invoker could simply assert. The proof is never logged or returned.
"""

import logging
from collections.abc import Callable
from typing import Any

from ..errors import ToolDenied
from ..security.identity import AnalystResolver
from ..types.run import TurnRun

logger = logging.getLogger(__name__)

PROOF_FIELD = "caller_proof"
TurnRunner = Callable[..., TurnRun]


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "result": None, "error": {"code": code, "message": message}}


def handle(payload: Any, session_id: str | None, *, resolve_analyst: AnalystResolver, run: TurnRunner) -> dict[str, Any]:
    """ verify the caller, then run one turn; every denial is a structured result, never an exception or empty data """

    if not isinstance(payload, dict):
        return _error("invalid_input", "A JSON object is required")
    if not session_id:
        return _error("unauthenticated", "A runtime session is required")
    proof = payload.get(PROOF_FIELD)
    request = {key: value for key, value in payload.items() if key != PROOF_FIELD}
    try:
        analyst_id = resolve_analyst(proof if isinstance(proof, str) else "", session_id)
        result = run(request, analyst_id=analyst_id)
    except ToolDenied as denied:
        logger.info("runtime turn denied: %s", denied.code)
        return _error(denied.code, str(denied))
    return {"ok": True, "result": result.model_dump(mode="json"), "error": None}


def build_app(resolve_analyst: AnalystResolver, run: TurnRunner) -> Any:
    """ the AgentCore app: POST /invocations runs handle(); GET /ping answers health checks """

    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: dict, context: Any) -> dict[str, Any]:
        return handle(payload, getattr(context, "session_id", None), resolve_analyst=resolve_analyst, run=run)

    return app


def main() -> None:
    """ serve /invocations and /ping on :8080, as AgentCore Runtime expects """

    from ..harness.run.wiring import turn
    from ..logging_context import configure_logging
    from ..security.identity import production_resolver

    configure_logging()
    build_app(production_resolver(), turn).run()


if __name__ == "__main__":
    main()
