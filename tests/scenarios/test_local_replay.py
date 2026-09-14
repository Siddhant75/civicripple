"""Five MVP acceptance scenarios, executed end-to-end in local replay mode.

Each test loads fixtures from disk and runs the real deterministic services:
assess_impact -> validate_route_candidate -> evaluate_feasibility ->
classify_incident. No AWS, no Strands, no mocks.
"""

import json
from pathlib import Path

from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import DisruptionEvent, OperationPlan, RouteCandidate
from civicripple.domain.policies import (
    HARD_CONSTRAINT_VIOLATION,
    ROUTE_AVOIDANCE_UNPROVEN,
    build_human_review_payload,
    classify_incident,
)
from civicripple.services.feasibility import evaluate_feasibility
from civicripple.services.geometry import assess_impact, validate_route_candidate

FIXTURES = Path("src/civicripple/fixtures")


def _load_plan() -> OperationPlan:
    return OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )


def _load_notice(relative: str) -> DisruptionEvent:
    return DisruptionEvent.model_validate_json((FIXTURES / relative).read_text())


def _load_candidate(relative: str) -> RouteCandidate:
    return RouteCandidate.model_validate_json((FIXTURES / relative).read_text())


def _scenario(name: str) -> dict:
    return json.loads((FIXTURES / "scenarios.json").read_text())[name]


def _affected_route(plan: OperationPlan, impact):
    return next(r for r in plan.routes if r.route_id in impact.affected_route_ids)


def _evaluate(notice_name: str, candidate_name: str | None):
    """Run the deterministic pipeline for one scenario."""
    plan = _load_plan()
    disruption = _load_notice(notice_name)
    impact = assess_impact(disruption, plan)

    candidate = None
    feasibility = None
    if candidate_name is not None and impact.affected_route_ids:
        raw_candidate = _load_candidate(candidate_name)
        candidate = validate_route_candidate(raw_candidate, disruption)
        if candidate.independently_clear_of_disruption:
            route = _affected_route(plan, impact)
            feasibility = evaluate_feasibility(route, candidate)

    decision = classify_incident(impact, candidate=candidate, feasibility=feasibility)
    return plan, disruption, impact, candidate, feasibility, decision


def test_scenario_a_irrelevant_notice_is_no_impact() -> None:
    scenario = _scenario("no_impact")
    *_, decision = _evaluate(scenario["notice"], scenario["route_candidate"])
    assert decision.classification is DecisionClassification.NO_IMPACT
    assert decision.permitted_action is None


def test_scenario_b_feasible_reroute_is_auto_resolvable() -> None:
    scenario = _scenario("feasible_reroute")
    plan, disruption, impact, candidate, feasibility, decision = _evaluate(
        scenario["notice"], scenario["route_candidate"]
    )
    assert impact.affected_route_ids == scenario["affected_route_ids"]
    assert candidate is not None and candidate.independently_clear_of_disruption
    assert feasibility is not None and feasibility.feasible
    assert decision.classification is DecisionClassification.AUTO_RESOLVABLE
    assert decision.permitted_action == "APPLY_INTERNAL_REROUTE"


def test_scenario_c_infeasible_reroute_requires_human() -> None:
    scenario = _scenario("infeasible_reroute")
    plan, disruption, impact, candidate, feasibility, decision = _evaluate(
        scenario["notice"], scenario["route_candidate"]
    )
    assert candidate is not None and candidate.independently_clear_of_disruption
    assert feasibility is not None and not feasibility.feasible
    assert decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert decision.review_reason == HARD_CONSTRAINT_VIOLATION


def test_scenario_d_avoidance_failure_is_rejected() -> None:
    scenario = _scenario("avoidance_failure")
    plan, disruption, impact, candidate, feasibility, decision = _evaluate(
        scenario["notice"], scenario["route_candidate"]
    )
    assert candidate is not None
    assert candidate.independently_clear_of_disruption is False
    # Rejected before feasibility is even evaluated.
    assert feasibility is None
    assert decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert decision.review_reason == ROUTE_AVOIDANCE_UNPROVEN


def test_scenario_e_review_payload_names_stops_and_constraints() -> None:
    scenario = _scenario("human_review_payload")
    plan, disruption, impact, candidate, feasibility, decision = _evaluate(
        scenario["notice"], scenario["route_candidate"]
    )
    payload = build_human_review_payload(
        "incident-replay-e", impact, feasibility, decision.review_reason
    )
    assert payload.affected_stop_ids == ["stop-b1", "stop-b2"]
    failed = [v.stop_id for v in payload.failed_constraints]
    assert "stop-b2" in failed
    assert all(v.code == "TIME_WINDOW_LATE" for v in payload.failed_constraints)
    assert payload.reason == HARD_CONSTRAINT_VIOLATION
