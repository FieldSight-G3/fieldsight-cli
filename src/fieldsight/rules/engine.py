from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.rules.confidence import confidence_floor
from fieldsight.rules.log_classification import log_classification
from fieldsight.rules.recordability import recordability
from fieldsight.rules.reporting import reporting_clock
from fieldsight.rules.treatment import medical_treatment
from fieldsight.schemas.incidents import NormalizedIncident
from fieldsight.schemas.rule_decision import RuleDecision
from fieldsight.schemas.rule_input import (
    AdmissionReason,
    AmputationDetail,
    EventType,
    R1Inputs,
    R2Inputs,
    R3Inputs,
    R4Inputs,
    R5Inputs,
)
from fieldsight.schemas.run_records import RuleInvocation


class IncidentRuleResults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: RuleDecision
    treatment: RuleDecision | None = None
    recordability: RuleDecision | None = None
    reporting: RuleDecision | None = None
    log_classification: RuleDecision | None = None

    invocations: list[RuleInvocation] = Field(default_factory=list)


def evaluate_incident(
    incident: NormalizedIncident,
) -> IncidentRuleResults:
    invocations: list[RuleInvocation] = []

    r5 = confidence_floor(
        R5Inputs(confidences=incident.confidences)
    )
    invocations.append(create_invocation(incident.incident_id, r5))

    if r5.outcome != "ready":
        return IncidentRuleResults(
            confidence=r5,
            invocations=invocations,
        )

    r3 = medical_treatment(
        R3Inputs(treatments=incident.treatments)
    )
    invocations.append(create_invocation(incident.incident_id, r3))

    r1 = recordability(
        R1Inputs(
            work_related=incident.work_related,
            new_case=incident.new_case,
            death=incident.death,
            days_away=incident.days_away,
            restricted_days=incident.restricted_days,
            job_transfer=incident.job_transfer,
            medical_treatment_beyond_first_aid={
                "beyond_first_aid": True,
                "first_aid_only": False
                }.get(r3.outcome),
            loss_of_consciousness=incident.loss_of_consciousness,
            significant_diagnosis=incident.significant_diagnosis,
        )
    )
    invocations.append(create_invocation(incident.incident_id, r1))

    r2 = reporting_clock(
        R2Inputs(
            work_related=incident.work_related,
            event_type=cast(
                EventType | None,
                incident.event_type,
            ),
            incident_at=incident.incident_at,
            event_at=incident.event_at,
            learned_at=incident.learned_at,
            admission_reason=cast(
                AdmissionReason | None,
                incident.admission_reason,
            ),
            amputation_detail=cast(
                AmputationDetail | None,
                incident.amputation_detail,
            ),
        )
    )
    invocations.append(create_invocation(incident.incident_id, r2))

    r4 = log_classification(
    R4Inputs(
        recordable={
            "recordable": True,
            "not_recordable": False
        }.get(r1.outcome),
        death=incident.death,
        days_away=incident.days_away,
        restricted_days=incident.restricted_days,
        job_transfer=incident.job_transfer
    )
)
    invocations.append(create_invocation(incident.incident_id, r4))

    return IncidentRuleResults(
        confidence=r5,
        treatment=r3,
        recordability=r1,
        reporting=r2,
        log_classification=r4,
        invocations=invocations,
    )

def create_invocation(
    incident_id: str,
    decision: RuleDecision,
) -> RuleInvocation:
    return RuleInvocation(
        incident_id=incident_id,
        recorded_at=datetime.now(UTC),
        decision=decision,
    )