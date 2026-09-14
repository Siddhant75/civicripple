from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from civicripple.domain.enums import DecisionClassification, DisruptionType, IncidentState
from civicripple.domain.models import (
    DisruptionEvent,
    GeoShape,
    LocationPoint,
    OperationPlan,
    RouteCandidate,
    TimeWindow,
)


def test_location_point_rejects_invalid_latitude() -> None:
    with pytest.raises(ValidationError):
        LocationPoint(lat=95.0, lon=10.0)


def test_location_point_rejects_invalid_longitude() -> None:
    with pytest.raises(ValidationError):
        LocationPoint(lat=10.0, lon=200.0)


def test_time_window_rejects_reverse_interval() -> None:
    start = datetime(2026, 9, 3, 9, tzinfo=timezone.utc)
    end = datetime(2026, 9, 3, 8, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        TimeWindow(start=start, end=end)


def test_geo_shape_accepts_linestring_coordinates() -> None:
    shape = GeoShape(kind="LineString", coordinates=[[-122.4, 47.6], [-122.3, 47.7]])
    assert shape.kind == "LineString"


def test_geo_shape_rejects_unsupported_kind() -> None:
    with pytest.raises(ValidationError):
        GeoShape(kind="MultiPolygon", coordinates=[[[[0.0, 0.0]]]])


def test_road_closure_enum_is_stable() -> None:
    assert DisruptionType.ROAD_CLOSURE.value == "ROAD_CLOSURE"


def test_incident_state_covers_architecture_states() -> None:
    expected = {
        "DETECTED",
        "EXTRACTED",
        "VERIFIED",
        "IMPACT_ASSESSED",
        "NO_IMPACT",
        "ROUTE_REQUESTED",
        "CANDIDATE_REJECTED",
        "CANDIDATE_VALIDATED",
        "FEASIBLE",
        "INFEASIBLE",
        "POLICY_EVALUATED",
        "AUTO_APPROVED",
        "REVIEW_REQUIRED",
        "HUMAN_APPROVED",
        "HUMAN_REJECTED",
        "RESOLVED",
        "OPEN",
    }
    assert {state.value for state in IncidentState} == expected


def test_operation_fixture_matches_operation_plan_schema() -> None:
    raw = Path("src/civicripple/fixtures/operation_plan.json").read_text()
    plan = OperationPlan.model_validate_json(raw)
    assert plan.operation_id == "op-demo-2026-09-03"
    assert len(plan.routes) == 2
    assert sum(len(route.stops) for route in plan.routes) == 8


def test_operation_fixture_contains_no_pii() -> None:
    raw = Path("src/civicripple/fixtures/operation_plan.json").read_text().lower()
    for marker in ("phone", "email", "medical", "patient"):
        assert marker not in raw


def test_all_replay_fixtures_validate() -> None:
    root = Path("src/civicripple/fixtures")
    notices = list((root / "notices").glob("*.json"))
    candidates = list((root / "route_candidates").glob("*.json"))
    assert len(notices) == 3
    assert len(candidates) == 3
    for path in notices:
        DisruptionEvent.model_validate_json(path.read_text())
    for path in candidates:
        RouteCandidate.model_validate_json(path.read_text())

    scenarios = json.loads((root / "scenarios.json").read_text())
    assert scenarios["no_impact"]["expected"] == DecisionClassification.NO_IMPACT
    assert scenarios["feasible_reroute"]["expected"] == DecisionClassification.AUTO_RESOLVABLE
    assert scenarios["infeasible_reroute"]["expected"] == DecisionClassification.HUMAN_DECISION_REQUIRED
    assert scenarios["avoidance_failure"]["expected"] == DecisionClassification.HUMAN_DECISION_REQUIRED
    assert scenarios["human_review_payload"]["expected"] == DecisionClassification.HUMAN_DECISION_REQUIRED
    assert len(scenarios) == 5
