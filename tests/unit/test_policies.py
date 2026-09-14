from pathlib import Path

from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import DisruptionEvent, OperationPlan, RouteCandidate
from civicripple.domain.policies import build_human_review_payload, classify_incident
from civicripple.services.feasibility import evaluate_feasibility
from civicripple.services.geometry import assess_impact, validate_route_candidate

FIXTURES = Path("src/civicripple/fixtures")


def _load_plan() -> OperationPlan:
    return OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )


def _load_notice(name: str) -> DisruptionEvent:
    return DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / name).read_text()
    )


def _load_candidate(name: str) -> RouteCandidate:
    return RouteCandidate.model_validate_json(
        (FIXTURES / "route_candidates" / name).read_text()
    )


def _route(plan: OperationPlan):
    return next(r for r in plan.routes if r.route_id == "route-b")


def test_no_affected_legs_is_no_impact() -> None:
    plan = _load_plan()
    impact = assess_impact(_load_notice("no_impact.json"), plan)
    decision = classify_incident(impact, candidate=None, feasibility=None)
    assert decision.classification is DecisionClassification.NO_IMPACT


def test_missing_candidate_requires_human_with_routing_unavailable() -> None:
    plan = _load_plan()
    impact = assess_impact(_load_notice("feasible_closure.json"), plan)
    decision = classify_incident(impact, candidate=None, feasibility=None)
    assert decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert decision.review_reason == "ROUTING_UNAVAILABLE"


def test_unclear_candidate_requires_human_with_avoidance_unproven() -> None:
    plan = _load_plan()
    disruption = _load_notice("feasible_closure.json")
    impact = assess_impact(disruption, plan)
    candidate = validate_route_candidate(_load_candidate("avoidance_violation.json"), disruption)
    decision = classify_incident(impact, candidate=candidate, feasibility=None)
    assert decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert decision.review_reason == "ROUTE_AVOIDANCE_UNPROVEN"


def test_infeasible_candidate_requires_human_with_hard_constraint() -> None:
    plan = _load_plan()
    disruption = _load_notice("infeasible_closure.json")
    impact = assess_impact(disruption, plan)
    candidate = validate_route_candidate(_load_candidate("infeasible.json"), disruption)
    feasibility = evaluate_feasibility(_route(plan), candidate)
    decision = classify_incident(impact, candidate=candidate, feasibility=feasibility)
    assert decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert decision.review_reason == "HARD_CONSTRAINT_VIOLATION"


def test_safe_feasible_candidate_is_auto_resolvable() -> None:
    plan = _load_plan()
    disruption = _load_notice("feasible_closure.json")
    impact = assess_impact(disruption, plan)
    candidate = validate_route_candidate(_load_candidate("feasible.json"), disruption)
    feasibility = evaluate_feasibility(_route(plan), candidate)
    decision = classify_incident(impact, candidate=candidate, feasibility=feasibility)
    assert decision.classification is DecisionClassification.AUTO_RESOLVABLE
    assert decision.permitted_action == "APPLY_INTERNAL_REROUTE"


def test_review_payload_names_stops_and_constraints() -> None:
    plan = _load_plan()
    disruption = _load_notice("infeasible_closure.json")
    impact = assess_impact(disruption, plan)
    candidate = validate_route_candidate(_load_candidate("infeasible.json"), disruption)
    feasibility = evaluate_feasibility(_route(plan), candidate)
    payload = build_human_review_payload(
        "incident-demo-1", impact, feasibility, "HARD_CONSTRAINT_VIOLATION"
    )
    assert payload.incident_id == "incident-demo-1"
    assert payload.affected_stop_ids == ["stop-b1", "stop-b2"]
    assert [v.stop_id for v in payload.failed_constraints] == ["stop-b2"]
    assert payload.failed_constraints[0].code == "TIME_WINDOW_LATE"
    assert payload.reason == "HARD_CONSTRAINT_VIOLATION"
