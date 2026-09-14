from datetime import datetime, timedelta, timezone
from pathlib import Path

from civicripple.domain.models import DisruptionEvent, OperationPlan, RouteCandidate
from civicripple.services.geometry import (
    assess_impact,
    intervals_overlap,
    validate_route_candidate,
)

FIXTURES = Path("src/civicripple/fixtures")


def _load_plan() -> OperationPlan:
    return OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )


def _load_notice(name: str) -> DisruptionEvent:
    return DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / name).read_text()
    )


def test_touching_interval_boundary_is_not_overlap() -> None:
    t0 = datetime(2026, 9, 3, 8, tzinfo=timezone.utc)
    assert not intervals_overlap(
        t0, t0 + timedelta(hours=1), t0 + timedelta(hours=1), t0 + timedelta(hours=2)
    )


def test_overlapping_intervals_overlap() -> None:
    t0 = datetime(2026, 9, 3, 8, tzinfo=timezone.utc)
    assert intervals_overlap(
        t0, t0 + timedelta(hours=1), t0 + timedelta(minutes=30), t0 + timedelta(hours=2)
    )


def test_no_impact_fixture_yields_zero_affected_legs() -> None:
    impact = assess_impact(_load_notice("no_impact.json"), _load_plan())
    assert impact.affected_route_ids == []
    assert impact.affected_leg_ids == []
    assert impact.affected_stop_ids == []
    assert "NO_IMPACT" not in impact.reasons


def test_feasible_closure_affects_route_b_leg_b2() -> None:
    impact = assess_impact(_load_notice("feasible_closure.json"), _load_plan())
    assert impact.affected_route_ids == ["route-b"]
    assert impact.affected_leg_ids == ["leg-b2"]
    assert impact.affected_stop_ids == ["stop-b1", "stop-b2"]


def test_reasons_contain_deterministic_fact_labels() -> None:
    impact = assess_impact(_load_notice("feasible_closure.json"), _load_plan())
    assert "temporal_overlap:leg-b2" in impact.reasons
    assert "spatial_overlap:leg-b2" in impact.reasons


def test_no_impact_fixture_reports_spatial_overlap_false() -> None:
    impact = assess_impact(_load_notice("no_impact.json"), _load_plan())
    assert impact.spatial_overlap is False


def test_infeasible_closure_affects_same_corridor() -> None:
    impact = assess_impact(_load_notice("infeasible_closure.json"), _load_plan())
    assert impact.affected_leg_ids == ["leg-b2"]


def _load_candidate(name: str) -> RouteCandidate:
    return RouteCandidate.model_validate_json(
        (FIXTURES / "route_candidates" / name).read_text()
    )


def test_candidate_rejected_when_provider_reports_avoidance_violation() -> None:
    candidate = _load_candidate("avoidance_violation.json")
    disruption = _load_notice("feasible_closure.json")
    validated = validate_route_candidate(candidate, disruption)
    assert validated.independently_clear_of_disruption is False


def test_candidate_rejected_when_geometry_still_intersects() -> None:
    disruption = _load_notice("feasible_closure.json")
    candidate = _load_candidate("feasible.json").model_copy(
        update={"provider_notices": []},
    )
    # Sabotage: reuse the violation candidate's geometry (intersects closure)
    # while clearing the provider notices, so only geometry can reject it.
    violating_geometry = _load_candidate("avoidance_violation.json").geometry
    candidate = candidate.model_copy(update={"geometry": violating_geometry})
    validated = validate_route_candidate(candidate, disruption)
    assert validated.independently_clear_of_disruption is False


def test_clean_candidate_is_accepted() -> None:
    candidate = _load_candidate("feasible.json")
    disruption = _load_notice("feasible_closure.json")
    validated = validate_route_candidate(candidate, disruption)
    assert validated.independently_clear_of_disruption is True


def test_validation_does_not_mutate_original_candidate() -> None:
    candidate = _load_candidate("avoidance_violation.json")
    disruption = _load_notice("feasible_closure.json")
    validated = validate_route_candidate(candidate, disruption)
    assert validated is not candidate
    assert candidate.independently_clear_of_disruption is False
    assert validated.independently_clear_of_disruption is False
