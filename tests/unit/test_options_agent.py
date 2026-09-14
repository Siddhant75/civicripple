from pathlib import Path

from civicripple.agents.options_agent import (
    build_options_agent,
    explain_options,
    options_match_impact,
)
from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import (
    DisruptionEvent,
    ImpactAssessment,
    IncidentDecision,
    OperationPlan,
    OptionsReport,
    RouteCandidate,
)
from civicripple.services.feasibility import evaluate_feasibility
from civicripple.services.geometry import assess_impact, validate_route_candidate
from civicripple.services.replay_model import ReplayModel

FIXTURES = Path("src/civicripple/fixtures")


def _scenario_inputs():
    plan = OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )
    disruption = DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / "infeasible_closure.json").read_text()
    )
    impact = assess_impact(disruption, plan)
    candidate = validate_route_candidate(
        RouteCandidate.model_validate_json(
            (FIXTURES / "route_candidates" / "infeasible.json").read_text()
        ),
        disruption,
    )
    route = next(r for r in plan.routes if r.route_id == "route-b")
    feasibility = evaluate_feasibility(route, candidate)
    decision = IncidentDecision(
        classification=DecisionClassification.HUMAN_DECISION_REQUIRED,
        review_reason="HARD_CONSTRAINT_VIOLATION",
    )
    return impact, decision, feasibility


def _scripted_report() -> OptionsReport:
    return OptionsReport.model_validate_json(
        (FIXTURES / "model_replays" / "infeasible_reroute" / "options.json").read_text()
    )


def test_options_agent_returns_bounded_report() -> None:
    impact, decision, feasibility = _scenario_inputs()
    agent = build_options_agent(ReplayModel([_scripted_report()]))
    report = explain_options(agent, "incident-replay-c", decision, impact, feasibility)
    assert report.incident_id == "incident-replay-c"
    assert len(report.options) >= 1
    assert all(o.requires_human_approval for o in report.options)


def test_options_must_match_impact_exactly() -> None:
    impact, _, _ = _scenario_inputs()
    assert options_match_impact(_scripted_report(), impact) is True
    tampered = _scripted_report().model_copy(update={"affected_stop_ids": ["stop-b9"]})
    assert options_match_impact(tampered, impact) is False
