"""The five MVP acceptance scenarios executed through the full Strands
orchestration graph in MODE=local_replay. Real deterministic services, real
Strands graph, scripted replay models — no AWS, no network, no mocks of
business logic."""

import json
from pathlib import Path

from civicripple.domain.enums import DecisionClassification, IncidentState
from civicripple.orchestration.replay import run_replay_scenario

FIXTURES = Path("src/civicripple/fixtures")


def _run_scenario(key: str):
    run = run_replay_scenario(key, correlation_id=f"incident-phase2-{key}")
    item = json.loads((FIXTURES / "scenarios.json").read_text())[key]
    return run.ctx, run.trail, run.store, item


def test_scenario_a_irrelevant_notice_resolves_no_impact() -> None:
    ctx, trail, store, item = _run_scenario("no_impact")
    assert ctx.decision.classification.value == item["expected"]
    assert ctx.state is IncidentState.RESOLVED


def test_scenario_b_feasible_reroute_auto_resolves() -> None:
    ctx, trail, store, item = _run_scenario("feasible_reroute")
    assert ctx.decision.classification.value == item["expected"]
    assert ctx.state is IncidentState.RESOLVED
    assert store.get("incident-phase2-feasible_reroute").state is IncidentState.RESOLVED


def test_scenario_c_infeasible_reroute_requires_human() -> None:
    ctx, trail, store, item = _run_scenario("infeasible_reroute")
    assert ctx.decision.classification.value == item["expected"]
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.options is not None
    assert store.get("incident-phase2-infeasible_reroute").review_payload is not None


def test_scenario_d_avoidance_failure_is_rejected_by_graph() -> None:
    ctx, trail, store, item = _run_scenario("avoidance_failure")
    assert ctx.decision.classification.value == item["expected"]
    assert ctx.decision.review_reason == "ROUTE_AVOIDANCE_UNPROVEN"
    assert ctx.feasibility is None
    assert ctx.state is IncidentState.REVIEW_REQUIRED


def test_scenario_e_audit_trail_is_complete_and_deterministic() -> None:
    ctx, trail, store, _ = _run_scenario("infeasible_reroute")
    events = trail.events_for("incident-phase2-infeasible_reroute")
    states = [(e.state_from, e.state_to) for e in events]
    # Full deterministic path: DETECTED -> EXTRACTED -> VERIFIED ->
    # IMPACT_ASSESSED -> ROUTE_REQUESTED -> CANDIDATE_VALIDATED ->
    # INFEASIBLE -> POLICY_EVALUATED -> REVIEW_REQUIRED -> REVIEW_REQUIRED
    assert states == [
        (IncidentState.DETECTED, IncidentState.DETECTED),
        (IncidentState.DETECTED, IncidentState.EXTRACTED),
        (IncidentState.EXTRACTED, IncidentState.VERIFIED),
        (IncidentState.VERIFIED, IncidentState.IMPACT_ASSESSED),
        (IncidentState.IMPACT_ASSESSED, IncidentState.ROUTE_REQUESTED),
        (IncidentState.ROUTE_REQUESTED, IncidentState.ROUTE_REQUESTED),
        (IncidentState.ROUTE_REQUESTED, IncidentState.CANDIDATE_VALIDATED),
        (IncidentState.CANDIDATE_VALIDATED, IncidentState.INFEASIBLE),
        (IncidentState.INFEASIBLE, IncidentState.POLICY_EVALUATED),
        (IncidentState.POLICY_EVALUATED, IncidentState.REVIEW_REQUIRED),
        (IncidentState.REVIEW_REQUIRED, IncidentState.REVIEW_REQUIRED),
        (IncidentState.REVIEW_REQUIRED, IncidentState.REVIEW_REQUIRED),
    ]
    assert all(e.mode == "local_replay" for e in events)
    payload = store.get("incident-phase2-infeasible_reroute").review_payload
    assert payload.affected_stop_ids == ["stop-b1", "stop-b2"]
    assert payload.failed_constraints[0].code == "TIME_WINDOW_LATE"
