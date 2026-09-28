"""Boundary and external-signal checks for the pure escalation policy."""

import unittest
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from fieldsight.escalation import (
    EscalationDecision,
    EscalationPolicy,
    EscalationSignals,
    evaluate_escalation,
)
from fieldsight.rules.engine import evaluate_incident
from fieldsight.schemas.incidents import NormalizedIncident

ORIGIN = datetime(2026, 1, 1, 9, tzinfo=UTC)
ALL_CLEAR = EscalationSignals(
    reviewer_approved=True,
    reviewer_iterations=1,
    citations_supported=True,
    retrieval_scores=[0.85, 0.91],
    prompt_attack_detected=False,
    photo_contradicts=False,
)


def incident(**changes: object) -> NormalizedIncident:
    data = {
        "incident_id": "case-1",
        "work_related": True,
        "new_case": True,
        "incident_at": ORIGIN,
        "event_at": None,
        "learned_at": None,
        "event_type": "other",
        "admission_reason": None,
        "amputation_detail": None,
        "treatments": [],
        "death": False,
        "days_away": 1,
        "restricted_days": 0,
        "job_transfer": False,
        "loss_of_consciousness": False,
        "significant_diagnosis": False,
        "confidences": {"work_related": 0.95},
    }
    data.update(changes)
    return NormalizedIncident.model_validate(data)


def decision(*, signals: EscalationSignals | None = ALL_CLEAR, **changes: object) -> EscalationDecision:
    facts = incident(**changes)
    return evaluate_escalation(facts, evaluate_incident(facts), signals=signals)


class EscalationTests(unittest.TestCase):
    def test_all_checks_evaluated_and_no_review_for_clear_case(self) -> None:
        result = decision()
        self.assertFalse(result.requires_review)
        self.assertTrue(result.eligible_for_auto_release)
        self.assertEqual(result.fired, [])
        self.assertEqual(len(result.checks), 10)
        self.assertTrue(all(check.evaluated for check in result.checks.values()))
        self.assertFalse(any(check.fired for check in result.checks.values()))
        self.assertEqual(result.model_dump(mode="json")["checks"]["retrieval"]["fired"], False)

    def test_absent_stage_signals_cannot_auto_release(self) -> None:
        result = decision(signals=None)
        self.assertFalse(result.requires_review)
        self.assertFalse(result.eligible_for_auto_release)
        for name in ("reviewer", "citation", "retrieval", "prompt_attack", "photo_contradiction"):
            with self.subTest(name=name):
                self.assertFalse(result.checks[name].evaluated)
                self.assertFalse(result.checks[name].fired)

    def test_confidence_floor_below_and_at_point_six(self) -> None:
        below = decision(confidences={"new_case": 0.599})
        at_floor = decision(confidences={"new_case": 0.60})
        self.assertTrue(below.checks["confidence_gate"].fired)
        self.assertEqual(below.checks["confidence_gate"].details["field"], "new_case")
        self.assertFalse(at_floor.checks["confidence_gate"].fired)
        self.assertTrue(at_floor.checks["near_boundary"].fired)

    def test_missing_rule_inputs_fire_even_when_reporting_does_not_run(self) -> None:
        result = decision(work_related=None)
        self.assertTrue(result.checks["insufficient_data"].fired)
        self.assertIn("R1", result.checks["insufficient_data"].details["rule_ids"])
        self.assertFalse(result.eligible_for_auto_release)

    def test_observation_only_admission_does_not_trigger_reportability(self) -> None:
        result = decision(
            event_type="inpatient_hospitalization",
            event_at=ORIGIN + timedelta(hours=10),
            learned_at=ORIGIN + timedelta(hours=11),
            admission_reason="observation_only",
        )
        self.assertFalse(result.checks["reportable_event"].fired)
        self.assertFalse(result.requires_review)

    def test_fatality_fires_even_outside_reporting_clock(self) -> None:
        result = decision(
            event_type="fatality", death=True,
            event_at=ORIGIN + timedelta(days=31),
            learned_at=ORIGIN + timedelta(days=31),
        )
        self.assertTrue(result.checks["fatality"].fired)
        self.assertFalse(result.checks["reportable_event"].fired)

    def test_reporting_24h_margin_has_fired_and_non_fired_examples(self) -> None:
        cases = [(23.75, True), (20, False)]
        for elapsed_hours, expected in cases:
            with self.subTest(hours=elapsed_hours):
                result = decision(
                    event_type="amputation", amputation_detail="traumatic_loss",
                    event_at=ORIGIN + timedelta(hours=elapsed_hours),
                    learned_at=ORIGIN + timedelta(hours=elapsed_hours),
                )
                self.assertEqual(result.checks["near_boundary"].fired, expected)
                self.assertTrue(result.checks["reportable_event"].fired)

    def test_fatality_30d_margin_has_fired_and_non_fired_examples(self) -> None:
        for elapsed_days, expected in ((29.5, True), (27, False)):
            with self.subTest(days=elapsed_days):
                result = decision(
                    event_type="fatality", death=True,
                    event_at=ORIGIN + timedelta(days=elapsed_days),
                    learned_at=ORIGIN + timedelta(days=elapsed_days),
                )
                self.assertEqual(result.checks["near_boundary"].fired, expected)
                self.assertTrue(result.checks["fatality"].fired)

    def test_log_180d_margin_uses_raw_day_count(self) -> None:
        for away_days, expected in ((179, True), (178, False), (182, False)):
            with self.subTest(days=away_days):
                result = decision(days_away=away_days)
                self.assertEqual(result.checks["near_boundary"].fired, expected)
                observation = next(
                    b for b in result.boundary_observations if b.name == "log_180d"
                )
                self.assertEqual(observation.value, away_days)

    def test_external_trigger_pairs_are_recorded_independently(self) -> None:
        pairs = (
            ("reviewer", {"reviewer_approved": False}, {"reviewer_approved": True}),
            ("reviewer", {"reviewer_iterations": 2}, {"reviewer_iterations": 1}),
            ("citation", {"citations_supported": False}, {"citations_supported": True}),
            ("retrieval", {"retrieval_scores": [0.59]}, {"retrieval_scores": [0.60]}),
            ("retrieval", {"retrieval_scores": []}, {"retrieval_scores": [0.85]}),
            ("prompt_attack", {"prompt_attack_detected": True}, {"prompt_attack_detected": False}),
            ("photo_contradiction", {"photo_contradicts": True}, {"photo_contradicts": False}),
        )
        for name, fired_inputs, clear_inputs in pairs:
            with self.subTest(name=name, inputs=fired_inputs):
                fired = decision(signals=ALL_CLEAR.model_copy(update=fired_inputs))
                clear = decision(signals=ALL_CLEAR.model_copy(update=clear_inputs))
                self.assertTrue(fired.checks[name].fired)
                self.assertIn(name, fired.fired)
                self.assertFalse(clear.checks[name].fired)
                self.assertNotIn(name, clear.fired)

    def test_configurable_margin_and_input_validation(self) -> None:
        facts = incident(confidences={"field": 0.62})
        rules = evaluate_incident(facts)
        default = evaluate_escalation(facts, rules, signals=ALL_CLEAR)
        narrower = evaluate_escalation(
            facts, rules, signals=ALL_CLEAR,
            policy=EscalationPolicy(confidence_margin_absolute=0.01),
        )
        self.assertTrue(default.checks["near_boundary"].fired)
        self.assertFalse(narrower.checks["near_boundary"].fired)
        with self.assertRaises(ValidationError):
            EscalationSignals(retrieval_scores=[1.01])


if __name__ == "__main__":
    unittest.main()
