from datetime import UTC, datetime, timedelta

import pytest

from fieldsight.rules.confidence import confidence_floor
from fieldsight.rules.log_classification import log_classification
from fieldsight.rules.reporting import reporting_clock
from fieldsight.schemas.rule_input import R2Inputs, R4Inputs, R5Inputs

INCIDENT = datetime(2026, 1, 1, tzinfo=UTC)


def r2_input(**changes) -> R2Inputs:
    values = {
        "work_related": True,
        "event_type": "fatality",
        "incident_at": INCIDENT,
        "event_at": INCIDENT,
        "learned_at": INCIDENT,
    }
    values.update(changes)
    return R2Inputs(**values)


def test_fatality_exactly_30_days_is_reportable() -> None:
    result = reporting_clock(
        r2_input(event_at=INCIDENT + timedelta(days=30))
    )

    assert result.outcome == "reportable"


def test_fatality_after_30_days_is_not_reportable() -> None:
    result = reporting_clock(
        r2_input(event_at=INCIDENT + timedelta(days=30, seconds=1))
    )

    assert result.outcome == "not_reportable"


def test_hospitalization_exactly_24_hours_is_reportable() -> None:
    result = reporting_clock(
        r2_input(
            event_type="inpatient_hospitalization",
            event_at=INCIDENT + timedelta(hours=24),
            admission_reason="care_or_treatment",
        )
    )

    assert result.outcome == "reportable"

def test_hospitalization_after_24_hours_is_not_reportable() -> None:
    result = reporting_clock(
        r2_input(
            event_type="inpatient_hospitalization",
            event_at=INCIDENT + timedelta(hours=24, seconds=1),
            admission_reason="care_or_treatment",
        )
    )

    assert result.outcome == "not_reportable"

@pytest.mark.parametrize("reason",["observation_only", "diagnostic_testing_only"])
def test_hospitalization_exclusions(reason: str) -> None:
    result = reporting_clock(
        r2_input(
            event_type="inpatient_hospitalization",
            admission_reason=reason,
        )
    )

    assert result.outcome == "not_reportable"


@pytest.mark.parametrize("detail",["avulsion","enucleation","degloving","scalping","severed_ear","broken_tooth","chipped_tooth"])
def test_amputation_exclusions(detail: str) -> None:
    result = reporting_clock(
        r2_input(
            event_type="amputation",
            amputation_detail=detail,
        )
    )

    assert result.outcome == "not_reportable"


def test_exactly_180_days_remains_180() -> None:
    result = log_classification(
        R4Inputs(
            recordable=True,
            death=False,
            days_away=100,
            restricted_days=80,
            job_transfer=False,
        )
    )

    assert result.log_column == "H"
    assert result.day_count == 180


def test_more_than_180_days_is_capped() -> None:
    result = log_classification(
        R4Inputs(
            recordable=True,
            death=False,
            days_away=150,
            restricted_days=100,
            job_transfer=False,
        )
    )

    assert result.day_count == 180


def test_exactly_point_60_passes() -> None:
    result = confidence_floor(
        R5Inputs(confidences={"event_type": 0.60})
    )

    assert result.outcome == "ready"


def test_below_point_60_requires_human() -> None:
    result = confidence_floor(
        R5Inputs(confidences={"event_type": 0.599})
    )

    assert result.outcome == "human_determination"