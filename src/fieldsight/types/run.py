""" shapes of one turn through the harness: what the workflow hands back, and what the turn produced """

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..harness.bounds import SessionUsage
from ..schemas.retrieval import Citation, RefusalReason
from ..schemas.review import ReviewVerdict
from ..schemas.run_records import ModelCall, RuleInvocation, ToolInvocation
from .dossier import Dossier
from .escalation import EscalationDecision, Score
from .guardrails import GuardrailEvent, Refusal, Route


class WorkflowResult(BaseModel):
    """ what the Coordinator's graph hands back once its eligibility check (guard_dossier) has run;
        None means the graph didn't report it, and escalation records it as unevaluated """

    model_config = ConfigDict(extra="forbid")

    dossier: Dossier
    workers_dispatched: list[str] = Field(default_factory=list)
    rule_invocations: list[RuleInvocation] = Field(default_factory=list)  # the guard's and the workers' own
    reviewer_approved: bool | None = None
    reviewer_iterations: int | None = Field(default=None, ge=0)
    citations_supported: bool | None = None
    blocked: dict[str, list[str]] = Field(default_factory=dict)  # legs still blocked when the caps ran out
    retrieval_scores: list[Score] | None = None
    events: list[GuardrailEvent] = Field(default_factory=list)

    # the turn's run record; cost and budget are the turn meter's, which prices every model call itself
    plans: list[dict] = Field(default_factory=list)
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    model_calls: list[ModelCall] = Field(default_factory=list)
    reviewer_verdicts: list[ReviewVerdict | None] = Field(default_factory=list)
    unavailable: dict[str, str] = Field(default_factory=dict)  # Gateway tools gone this turn -> why, for the analyst


class TurnRun(BaseModel):
    """ what one turn produced, for the CLI to render; the run record under run_id holds the same """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    correlation_id: UUID
    command: str
    route: Route | None
    refusal: Refusal | None = None
    problems: list[str] = Field(default_factory=list)  # why readiness stopped a classify turn
    answer: str | None = None
    retrieval_refusal: RefusalReason | None = None  # the answer is the retrieval chain's refusal, for this reason
    sources: list[Citation] = Field(default_factory=list)
    dossier: Dossier | None = None
    blocked: dict[str, list[str]] = Field(default_factory=dict)
    unavailable: dict[str, str] = Field(default_factory=dict)  # Gateway tools gone this turn -> why
    escalation: EscalationDecision | None = None
    events: list[GuardrailEvent] = Field(default_factory=list)
    usage: SessionUsage | None = None
