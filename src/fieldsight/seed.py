"""Repeatable synthetic analysts, establishment grants and historical incidents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fieldsight.repository import SeedRepository, SeedSummary
from fieldsight.schemas.incidents import NormalizedIncident

NORTH = "North Substation"
CENTRAL = "Central Substation"
SOUTH = "South Substation"
ESTABLISHMENTS = (NORTH, CENTRAL, SOUTH)

def stable_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fieldsight/synthetic-history/{name}")

ALICE = stable_id("analyst-alice")
BOB = stable_id("analyst-bob")
CAROL = stable_id("analyst-carol")

@dataclass(frozen=True)
class Case:
    key: str
    narrative: str
    recordability: str
    reporting: str
    deciding_rule: str
    fields: dict[str, Any]
    event_delay: timedelta | None = None
    confidence: float = 0.95

CASES = (
    Case("fatality_day_29", "A worker died after a work-related fall, 29 days after the incident.",
         "recordable", "reportable", "R2", {"death": True, "event_type": "fatality"}, timedelta(days=29)),
    Case("fatality_day_30", "A worker died exactly 30 days after a work-related incident.",
         "recordable", "reportable", "R2", {"death": True, "event_type": "fatality"}, timedelta(days=30)),
    Case("fatality_after_30", "A worker died 30 days and one second after a work-related incident.",
         "recordable", "not_reportable", "R2", {"death": True, "event_type": "fatality"}, timedelta(days=30, seconds=1)),
    Case("hospital_before_24", "A worker was formally admitted for treatment before 24 hours had passed.",
         "recordable", "reportable", "R2", {"event_type": "inpatient_hospitalization", "admission_reason": "care_or_treatment", "days_away": 1}, timedelta(hours=23, minutes=59, seconds=59)),
    Case("hospital_at_24", "A worker was formally admitted for treatment exactly 24 hours after the incident.",
         "recordable", "reportable", "R2", {"event_type": "inpatient_hospitalization", "admission_reason": "care_or_treatment", "days_away": 1}, timedelta(hours=24)),
    Case("hospital_after_24", "A worker was admitted for treatment 24 hours and one second after the incident.",
         "recordable", "not_reportable", "R2", {"event_type": "inpatient_hospitalization", "admission_reason": "care_or_treatment", "days_away": 1}, timedelta(hours=24, seconds=1)),
    Case("days_away_179", "A technician was away from work for 179 calendar days.",
         "recordable", "not_reportable", "R4", {"days_away": 179}),
    Case("days_away_180", "A technician was away from work for 180 calendar days.",
         "recordable", "not_reportable", "R4", {"days_away": 180}),
    Case("days_away_181", "A technician was away from work for 181 calendar days, subject to the log cap.",
         "recordable", "not_reportable", "R4", {"days_away": 181}),
    Case("confidence_059", "An injury date was hard to read and required analyst verification.",
         "recordable", "not_reportable", "R1", {"days_away": 1}, confidence=0.59),
    Case("confidence_060", "An injury date had exactly the minimum extraction confidence.",
         "recordable", "not_reportable", "R1", {"days_away": 1}, confidence=0.60),
    Case("confidence_061", "An injury date was just above the minimum extraction confidence.",
         "recordable", "not_reportable", "R1", {"days_away": 1}, confidence=0.61),
    Case("observation_only", "A worker stayed overnight for observation only, then missed a day of work.",
         "recordable", "not_reportable", "R2", {"event_type": "inpatient_hospitalization", "admission_reason": "observation_only", "days_away": 1}, timedelta(hours=10)),
    Case("avulsion_exclusion", "An avulsion caused a day away, without a reportable amputation.",
         "recordable", "not_reportable", "R2", {"event_type": "amputation", "amputation_detail": "avulsion", "days_away": 1}, timedelta(hours=10)),
    Case("traumatic_amputation", "A traumatic amputation occurred within 24 hours of a work-related incident.",
         "recordable", "reportable", "R2", {"event_type": "amputation", "amputation_detail": "traumatic_loss", "days_away": 1}, timedelta(hours=10)),
    Case("first_aid_only", "A worker received first aid and returned to normal work.",
         "not_recordable", "not_reportable", "R1", {"treatments": []}),
    Case("prescription_treatment", "A worker received prescription medication for a work-related injury.",
         "recordable", "not_reportable", "R1", {"treatments": ["prescription_medication"]}),
    Case("missing_work_relation", "The packet omitted work relationship; a human later verified the closed case.",
         "recordable", "not_reportable", "R1", {"work_related": None, "days_away": 1}),
    Case("outside_work", "An injury away from work caused a day away but was not work-related.",
         "not_recordable", "not_reportable", "R1", {"work_related": False, "days_away": 1})
)

def analysts() -> list[dict[str, Any]]:
    return [
        {"analyst_id": ALICE, "external_subject": "seed:alice", "display_name": "Alice Example"},
        {"analyst_id": BOB, "external_subject": "seed:bob", "display_name": "Bob Example"},
        {"analyst_id": CAROL, "external_subject": "seed:carol", "display_name": "Carol Example"}
    ]

def grants() -> list[dict[str, Any]]:
    return [
        {"analyst_id": ALICE, "establishment": NORTH},
        {"analyst_id": ALICE, "establishment": CENTRAL},
        {"analyst_id": BOB, "establishment": SOUTH},
        {"analyst_id": CAROL, "establishment": CENTRAL}
    ]

def historical_incidents() -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for index, case in enumerate(CASES):
        incident_id = stable_id(case.key)
        establishment = ESTABLISHMENTS[index % len(ESTABLISHMENTS)]
        owner = ALICE if establishment == NORTH else BOB if establishment == SOUTH else CAROL
        start = datetime(2024 if index % 2 == 0 else 2026, 4, index + 1, 8, tzinfo=UTC)
        facts: dict[str, Any] = {
            "incident_id": str(incident_id),
            "work_related": True,
            "new_case": True,
            "incident_at": start,
            "event_at": None,
            "learned_at": None,
            "event_type": "other",
            "admission_reason": None,
            "amputation_detail": None,
            "treatments": [],
            "death": False,
            "days_away": 0,
            "restricted_days": 0,
            "job_transfer": False,
            "loss_of_consciousness": False,
            "significant_diagnosis": False
        }
        facts.update(case.fields)
        if case.event_delay is not None:
            facts["event_at"] = start + case.event_delay
            facts["learned_at"] = facts["event_at"] + timedelta(minutes=30)
        facts["confidences"] = {
            name: case.confidence if name == "incident_at" else 0.95
            for name, value in facts.items() if name != "incident_id" and value is not None
        }
        normalized = NormalizedIncident.model_validate(facts)
        outcome: dict[str, Any] = {
            "seed_case": case.key,
            "recordability": case.recordability,
            "reporting": case.reporting,
            "reviewed_by_human": True
        }
        if case.deciding_rule == "R4":
            outcome["log_days_away"] = min(normalized.days_away or 0, 180)
        incidents.append({
            "incident_id": incident_id,
            "establishment": establishment,
            "owner_analyst_id": owner,
            "normalized_fields": normalized.model_dump(mode="json"),
            "narrative": case.narrative,
            "outcome": outcome,
            "deciding_rule": case.deciding_rule,
            "status": "closed"
        })
    return incidents

def seed_demo() -> SeedSummary:
    return SeedRepository().seed(analysts(), grants(), historical_incidents())

def main() -> None:
    print(seed_demo().model_dump_json(indent=2))

if __name__ == "__main__":
    main()
