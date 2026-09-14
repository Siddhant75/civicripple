from pathlib import Path

from strands.multiagent.base import Status

from civicripple.agents.disruption_extractor import build_extractor_agent
from civicripple.agents.evidence_verifier import build_verifier_agent
from civicripple.agents.options_agent import build_options_agent
from civicripple.domain.enums import DecisionClassification, IncidentState
from civicripple.domain.models import (
    DisruptionEventCandidate,
    OptionsReport,
    VerificationVerdict,
)
from civicripple.orchestration.context import CONTEXT_KEY, IncidentContext
from civicripple.orchestration.graph import build_incident_graph
from civicripple.services.audit import AuditTrail
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.replay_model import ReplayModel
from civicripple.services.routing import ReplayRoutingProvider
from civicripple.services.storage import InMemoryIncidentStore

FIXTURES = Path("src/civicripple/fixtures")


def _run_graph(notice: str, scenario: str, candidate: str, options: bool):
    replays = FIXTURES / "model_replays" / scenario
    extractor = build_extractor_agent(
        ReplayModel(
            [DisruptionEventCandidate.model_validate_json((replays / "extractor.json").read_text())]
        )
    )
    verifier = build_verifier_agent(
        ReplayModel([VerificationVerdict.model_validate_json((replays / "verifier.json").read_text())])
    )
    if options:
        options_agent = build_options_agent(
            ReplayModel([OptionsReport.model_validate_json((replays / "options.json").read_text())])
        )
    else:
        options_agent = build_options_agent(ReplayModel([]))  # must never be invoked
    trail = AuditTrail()
    store = InMemoryIncidentStore()
    graph = build_incident_graph(
        extractor=extractor,
        verifier=verifier,
        options_agent=options_agent,
        source=ReplayCivicSource(notice_name=notice),
        routing=ReplayRoutingProvider(candidate_name=candidate),
        trail=trail,
        store=store,
    )
    ctx = IncidentContext(
        correlation_id=f"incident-{scenario}",
        mode="local_replay",
        source_url=f"https://replay.example/notices/{notice.removesuffix('.txt')}",
    )
    invocation_state = {CONTEXT_KEY: ctx}
    result = graph("process civic disruption incident", invocation_state=invocation_state)
    assert result.status is Status.COMPLETED
    return invocation_state[CONTEXT_KEY], trail, store


def test_graph_auto_resolves_feasible_reroute() -> None:
    ctx, trail, store = _run_graph(
        "feasible_closure.txt", "feasible_reroute", "feasible.json", options=False
    )
    assert ctx.state is IncidentState.RESOLVED
    assert ctx.decision.classification is DecisionClassification.AUTO_RESOLVABLE
    assert store.get("incident-feasible_reroute").state is IncidentState.RESOLVED


def test_graph_requires_human_for_infeasible_reroute() -> None:
    ctx, trail, store = _run_graph(
        "infeasible_closure.txt", "infeasible_reroute", "infeasible.json", options=True
    )
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.decision.review_reason == "HARD_CONSTRAINT_VIOLATION"
    assert ctx.options is not None
    record = store.get("incident-infeasible_reroute")
    assert record.review_payload.affected_stop_ids == ["stop-b1", "stop-b2"]


def test_graph_rejects_avoidance_violation() -> None:
    ctx, trail, store = _run_graph(
        "feasible_closure.txt", "avoidance_failure", "avoidance_violation.json", options=True
    )
    assert ctx.state is IncidentState.REVIEW_REQUIRED
    assert ctx.decision.review_reason == "ROUTE_AVOIDANCE_UNPROVEN"
    assert ctx.feasibility is None  # rejected before feasibility


def test_graph_resolves_irrelevant_notice() -> None:
    ctx, trail, store = _run_graph("no_impact.txt", "no_impact", "feasible.json", options=False)
    assert ctx.state is IncidentState.RESOLVED
    assert ctx.decision.classification is DecisionClassification.NO_IMPACT


def test_graph_audits_every_transition_with_correlation_id() -> None:
    ctx, trail, _ = _run_graph(
        "infeasible_closure.txt", "infeasible_reroute", "infeasible.json", options=True
    )
    events = trail.events_for("incident-infeasible_reroute")
    assert len(events) >= 8
    assert all(e.mode == "local_replay" for e in events)
    states = [(e.state_from, e.state_to) for e in events]
    assert states[0] == (IncidentState.DETECTED, IncidentState.DETECTED)
    assert states[-1] == (IncidentState.REVIEW_REQUIRED, IncidentState.REVIEW_REQUIRED)
