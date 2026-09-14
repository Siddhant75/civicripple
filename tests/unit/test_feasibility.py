from pathlib import Path

from civicripple.domain.models import OperationPlan, RouteCandidate
from civicripple.services.feasibility import evaluate_feasibility, propagate_arrivals

FIXTURES = Path("src/civicripple/fixtures")


def _load_route(route_id: str = "route-b"):
    plan = OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )
    return next(route for route in plan.routes if route.route_id == route_id)


def _load_candidate(name: str) -> RouteCandidate:
    return RouteCandidate.model_validate_json(
        (FIXTURES / "route_candidates" / name).read_text()
    )


def test_feasible_candidate_is_feasible_with_no_violations() -> None:
    result = evaluate_feasibility(_load_route(), _load_candidate("feasible.json"))
    assert result.feasible is True
    assert result.violations == []


def test_infeasible_candidate_violates_tight_time_window() -> None:
    result = evaluate_feasibility(_load_route(), _load_candidate("infeasible.json"))
    assert result.feasible is False
    late = [v for v in result.violations if v.code == "TIME_WINDOW_LATE"]
    assert len(late) >= 1
    assert late[0].stop_id == "stop-b2"
    assert late[0].lateness_s == 420


def test_added_duration_is_candidate_minus_original() -> None:
    route = _load_route()
    original = sum(leg.duration_s for leg in route.legs)
    result = evaluate_feasibility(route, _load_candidate("infeasible.json"))
    assert result.added_duration_s == 4200 - original


def test_distributed_leg_durations_sum_exactly() -> None:
    route = _load_route()
    original = sum(leg.duration_s for leg in route.legs)
    arrivals = propagate_arrivals(route, 4200)
    # First stop arrival = departure + first leg duration; final arrival
    # must reflect every distributed second, so total elapsed travel equals
    # the candidate duration when service times are excluded.
    total_with_service = (
        arrivals[-1].arrival_at - route.legs[0].planned_departure
    ).total_seconds()
    service_total = sum(
        stop.service_duration_s for stop in route.stops[:-1]
    )
    assert total_with_service - service_total == 4200


def test_stop_order_is_preserved() -> None:
    arrivals = propagate_arrivals(_load_route(), 3120)
    assert [a.stop_id for a in arrivals] == ["stop-b1", "stop-b2", "stop-b3", "stop-b4"]


def test_arrival_exactly_at_window_end_is_allowed() -> None:
    route = _load_route()
    # stop-b2 window ends 09:40. Candidate duration 3500 (= 3000 original
    # + 500 added, distributed 150/150/100/100) lands stop-b2 at exactly
    # 09:40: 09:00 + 1050s leg + 300s service + 1050s leg = 2400s.
    boundary_candidate = _load_candidate("feasible.json").model_copy(
        update={"duration_s": 3500}
    )
    result = evaluate_feasibility(route, boundary_candidate)
    b2 = next(a for a in result.stop_arrivals if a.stop_id == "stop-b2")
    assert b2.arrival_at.isoformat() == "2026-09-03T09:40:00+00:00"
    assert result.feasible is True
    assert result.violations == []
