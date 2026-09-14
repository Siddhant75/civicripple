from pathlib import Path

import pytest

from civicripple.domain.models import DisruptionEvent, OperationPlan
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.routing import ReplayRoutingProvider

FIXTURES = Path("src/civicripple/fixtures")


def _plan() -> OperationPlan:
    return OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )


def _disruption() -> DisruptionEvent:
    return DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / "feasible_closure.json").read_text()
    )


def _route(plan: OperationPlan, route_id: str):
    return next(r for r in plan.routes if r.route_id == route_id)


def test_replay_source_loads_plan_and_notice_text() -> None:
    source = ReplayCivicSource(notice_name="feasible_closure.txt")
    plan = source.load_plan()
    assert plan.operation_id == "op-demo-2026-09-03"
    text = source.load_notice_text()
    assert "REPLAYVILLE" in text  # raw municipal-notice text


def test_replay_source_rejects_missing_notice_fixture() -> None:
    source = ReplayCivicSource(notice_name="does_not_exist.txt")
    with pytest.raises(FileNotFoundError):
        source.load_notice_text()


def test_replay_routing_returns_candidate_for_matching_route() -> None:
    provider = ReplayRoutingProvider(candidate_name="feasible.json")
    plan = _plan()
    candidate = provider.request_candidate(plan, _route(plan, "route-b"), _disruption())
    assert candidate.route_id == "route-b"
    assert candidate.duration_s == 3120


def test_replay_routing_fails_closed_on_route_mismatch() -> None:
    provider = ReplayRoutingProvider(candidate_name="feasible.json")
    plan = _plan()
    with pytest.raises(RuntimeError):
        provider.request_candidate(plan, _route(plan, "route-a"), _disruption())
