from pathlib import Path

from civicripple.agents.disruption_extractor import build_extractor_agent
from civicripple.agents.evidence_verifier import build_verifier_agent
from civicripple.domain.enums import IncidentState, VerificationStatus
from civicripple.domain.models import (
    DisruptionEventCandidate,
    VerificationVerdict,
)
from civicripple.orchestration import nodes
from civicripple.orchestration.context import IncidentContext
from civicripple.services.audit import AuditTrail
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.replay_model import ReplayModel

FIXTURES = Path("src/civicripple/fixtures")


def _ctx(**overrides) -> IncidentContext:
    base = {
        "correlation_id": "incident-test",
        "mode": "local_replay",
        "source_url": "https://replay.example/notices/feasible-closure",
        "notice_text": "raw notice text",
    }
    base.update(overrides)
    return IncidentContext(**base)


def _scripted(scenario: str, name: str, model_cls):
    return model_cls.model_validate_json(
        (FIXTURES / "model_replays" / scenario / f"{name}.json").read_text()
    )


def test_observe_loads_plan_and_notice() -> None:
    trail = AuditTrail()
    source = ReplayCivicSource(notice_name="feasible_closure.txt")
    ctx = nodes.observe.run(_ctx(notice_text=None), source, trail)
    assert ctx.plan is not None and ctx.plan.operation_id == "op-demo-2026-09-03"
    assert "ROAD CLOSURE" in ctx.notice_text
    assert ctx.state is IncidentState.DETECTED
    assert trail.events_for("incident-test")[0].node == "observe"


def test_extract_promotes_candidate_and_transitions() -> None:
    trail = AuditTrail()
    agent = build_extractor_agent(
        ReplayModel([_scripted("feasible_reroute", "extractor", DisruptionEventCandidate)])
    )
    ctx = nodes.observe.run(
        _ctx(), ReplayCivicSource(notice_name="feasible_closure.txt"), trail
    )
    ctx = nodes.extract.run(ctx, agent, trail)
    assert ctx.state is IncidentState.EXTRACTED
    assert ctx.disruption is not None and ctx.disruption.event_id == "evt-feasible-closure"
    assert ctx.candidate is not None


def test_extract_failure_fails_closed_to_review() -> None:
    trail = AuditTrail()
    agent = build_extractor_agent(ReplayModel([]))  # no scripted response -> RuntimeError
    ctx = nodes.observe.run(
        _ctx(), ReplayCivicSource(notice_name="feasible_closure.txt"), trail
    )
    ctx = nodes.extract.run(ctx, agent, trail)
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.failure == "EXTRACTION_FAILED"
    assert ctx.disruption is None


def test_extract_rejects_invalid_candidate() -> None:
    trail = AuditTrail()
    bad = _scripted("feasible_reroute", "extractor", DisruptionEventCandidate).model_copy(
        update={"geometry": {"kind": "MultiPolygon", "coordinates": [[[[0.0, 0.0]]]]}}
    )
    agent = build_extractor_agent(ReplayModel([bad]))
    ctx = nodes.observe.run(
        _ctx(), ReplayCivicSource(notice_name="feasible_closure.txt"), trail
    )
    ctx = nodes.extract.run(ctx, agent, trail)
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.failure == "EXTRACTION_FAILED"


def test_verify_confirmed_candidate_advances() -> None:
    trail = AuditTrail()
    agent = build_verifier_agent(
        ReplayModel([_scripted("feasible_reroute", "verifier", VerificationVerdict)])
    )
    ctx = nodes.extract.run(
        _ctx(candidate=_scripted("feasible_reroute", "extractor", DisruptionEventCandidate)),
        build_extractor_agent(ReplayModel([])),
        trail,
    )
    ctx = nodes.verify.run(ctx, agent, trail)
    assert ctx.state is IncidentState.VERIFIED
    assert ctx.verdict.status is VerificationStatus.VERIFIED


def test_verify_unverified_fails_closed_to_review() -> None:
    trail = AuditTrail()
    unverified = _scripted("feasible_reroute", "verifier", VerificationVerdict).model_copy(
        update={"status": VerificationStatus.UNVERIFIED}
    )
    agent = build_verifier_agent(ReplayModel([unverified]))
    ctx = nodes.extract.run(
        _ctx(candidate=_scripted("feasible_reroute", "extractor", DisruptionEventCandidate)),
        build_extractor_agent(ReplayModel([])),
        trail,
    )
    ctx = nodes.verify.run(ctx, agent, trail)
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.failure == "UNVERIFIED_SOURCE"


def test_impact_assesses_and_marks_no_impact() -> None:
    trail = AuditTrail()
    source = ReplayCivicSource(notice_name="no_impact.txt")
    ctx = nodes.observe.run(
        _ctx(source_url="https://replay.example/notices/no-impact"), source, trail
    )
    ctx = nodes.extract.run(
        ctx,
        build_extractor_agent(
            ReplayModel([_scripted("no_impact", "extractor", DisruptionEventCandidate)])
        ),
        trail,
    )
    ctx = nodes.verify.run(
        ctx,
        build_verifier_agent(ReplayModel([_scripted("no_impact", "verifier", VerificationVerdict)])),
        trail,
    )
    ctx = nodes.impact.run(ctx, trail)
    assert ctx.impact is not None and ctx.impact.affected_leg_ids == []
    assert ctx.state is IncidentState.NO_IMPACT


def test_impact_affected_stays_at_impact_assessed() -> None:
    trail = AuditTrail()
    source = ReplayCivicSource(notice_name="feasible_closure.txt")
    ctx = nodes.observe.run(_ctx(), source, trail)
    ctx = nodes.extract.run(
        ctx,
        build_extractor_agent(
            ReplayModel([_scripted("feasible_reroute", "extractor", DisruptionEventCandidate)])
        ),
        trail,
    )
    ctx = nodes.verify.run(
        ctx,
        build_verifier_agent(ReplayModel([_scripted("feasible_reroute", "verifier", VerificationVerdict)])),
        trail,
    )
    ctx = nodes.impact.run(ctx, trail)
    assert ctx.impact.affected_leg_ids == ["leg-b2"]
    assert ctx.state is IncidentState.IMPACT_ASSESSED


def test_every_transition_is_audited_in_order() -> None:
    trail = AuditTrail()
    source = ReplayCivicSource(notice_name="feasible_closure.txt")
    ctx = nodes.observe.run(_ctx(), source, trail)
    ctx = nodes.extract.run(
        ctx,
        build_extractor_agent(
            ReplayModel([_scripted("feasible_reroute", "extractor", DisruptionEventCandidate)])
        ),
        trail,
    )
    ctx = nodes.verify.run(
        ctx,
        build_verifier_agent(ReplayModel([_scripted("feasible_reroute", "verifier", VerificationVerdict)])),
        trail,
    )
    ctx = nodes.impact.run(ctx, trail)
    states = [(e.state_from, e.state_to) for e in trail.events_for("incident-test")]
    assert (IncidentState.VERIFIED, IncidentState.IMPACT_ASSESSED) in states
    assert states[0][0] is IncidentState.DETECTED


# --- Task 10: route, geometry_validate, feasibility, policy, options, audit ---

from civicripple.agents.options_agent import build_options_agent
from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import OptionsReport
from civicripple.services.routing import ReplayRoutingProvider
from civicripple.services.storage import InMemoryIncidentStore


def _ctx_through_impact(notice: str, scenario: str) -> tuple:
    trail = AuditTrail()
    source = ReplayCivicSource(notice_name=notice)
    ctx = nodes.observe.run(_ctx(), source, trail)
    ctx = nodes.extract.run(
        ctx,
        build_extractor_agent(
            ReplayModel([_scripted(scenario, "extractor", DisruptionEventCandidate)])
        ),
        trail,
    )
    ctx = nodes.verify.run(
        ctx,
        build_verifier_agent(ReplayModel([_scripted(scenario, "verifier", VerificationVerdict)])),
        trail,
    )
    return nodes.impact.run(ctx, trail), trail


def test_route_requests_candidate() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="feasible.json"), trail)
    assert ctx.state is IncidentState.ROUTE_REQUESTED
    assert ctx.route_candidate is not None and ctx.route_candidate.duration_s == 3120


def test_route_provider_failure_leaves_no_candidate() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="does_not_exist.json"), trail)
    assert ctx.state is IncidentState.ROUTE_REQUESTED
    assert ctx.route_candidate is None
    assert ctx.failure == "ROUTING_UNAVAILABLE"


def test_geometry_validate_rejects_violating_candidate() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="avoidance_violation.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    assert ctx.state is IncidentState.CANDIDATE_REJECTED
    assert ctx.route_candidate.independently_clear_of_disruption is False


def test_geometry_validate_accepts_clean_candidate() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="feasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    assert ctx.state is IncidentState.CANDIDATE_VALIDATED
    assert ctx.route_candidate.independently_clear_of_disruption is True


def test_feasibility_marks_infeasible() -> None:
    ctx, trail = _ctx_through_impact("infeasible_closure.txt", "infeasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="infeasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    assert ctx.state is IncidentState.INFEASIBLE
    assert ctx.feasibility is not None and ctx.feasibility.feasible is False


def test_policy_auto_approves_feasible() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="feasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    assert ctx.state is IncidentState.AUTO_APPROVED
    assert ctx.decision.classification is DecisionClassification.AUTO_RESOLVABLE


def test_policy_routes_unsafe_candidate_to_review() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="avoidance_violation.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.decision.review_reason == "ROUTE_AVOIDANCE_UNPROVEN"


def test_policy_routes_missing_candidate_to_review() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="does_not_exist.json"), trail)
    ctx = nodes.policy.run(ctx, trail)
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.decision.review_reason == "ROUTING_UNAVAILABLE"


def test_options_node_records_bounded_report() -> None:
    ctx, trail = _ctx_through_impact("infeasible_closure.txt", "infeasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="infeasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    scripted = OptionsReport.model_validate_json(
        (FIXTURES / "model_replays" / "infeasible_reroute" / "options.json").read_text()
    )
    ctx = nodes.options.run(ctx, build_options_agent(ReplayModel([scripted])), trail)
    assert ctx.options is not None and len(ctx.options.options) == 3


def test_options_mismatch_fails_closed() -> None:
    ctx, trail = _ctx_through_impact("infeasible_closure.txt", "infeasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="infeasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    tampered = OptionsReport.model_validate_json(
        (FIXTURES / "model_replays" / "infeasible_reroute" / "options.json").read_text()
    ).model_copy(update={"affected_stop_ids": ["stop-b9"]})
    ctx = nodes.options.run(ctx, build_options_agent(ReplayModel([tampered])), trail)
    assert ctx.options is None
    assert ctx.failure == "OPTIONS_MISMATCH"


def test_audit_node_resolves_auto_approved() -> None:
    ctx, trail = _ctx_through_impact("feasible_closure.txt", "feasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="feasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    store = InMemoryIncidentStore()
    ctx = nodes.audit.run(ctx, trail, store)
    assert ctx.state is IncidentState.RESOLVED
    record = store.get("incident-test")
    assert record is not None and record.state is IncidentState.RESOLVED


def test_audit_node_leaves_human_incident_pending() -> None:
    ctx, trail = _ctx_through_impact("infeasible_closure.txt", "infeasible_reroute")
    ctx = nodes.route.run(ctx, ReplayRoutingProvider(candidate_name="infeasible.json"), trail)
    ctx = nodes.geometry_validate.run(ctx, trail)
    ctx = nodes.feasibility.run(ctx, trail)
    ctx = nodes.policy.run(ctx, trail)
    store = InMemoryIncidentStore()
    ctx = nodes.audit.run(ctx, trail, store)
    assert ctx.state is IncidentState.REVIEW_REQUIRED  # silence is never approval
    record = store.get("incident-test")
    assert record is not None and record.review_payload is not None
    assert record.review_payload.affected_stop_ids == ["stop-b1", "stop-b2"]


def test_audit_node_resolves_no_impact() -> None:
    ctx, trail = _ctx_through_impact("no_impact.txt", "no_impact")
    ctx = nodes.audit.run(ctx, trail, InMemoryIncidentStore())
    assert ctx.state is IncidentState.RESOLVED
    assert ctx.decision.classification is DecisionClassification.NO_IMPACT
