"""Strands orchestration graph for incident processing.

Conditional edges are typed predicates over the IncidentContext carried in
invocation_state — never string matching. Every node transition is audited
by the node itself; this module only wires control flow."""

from strands import Agent
from strands.multiagent import GraphBuilder
from strands.multiagent.graph import Graph

from civicripple.domain.enums import (
    DecisionClassification,
    VerificationStatus,
)
from civicripple.orchestration.context import CONTEXT_KEY, IncidentContext
from civicripple.orchestration.nodes import (
    audit,
    extract,
    feasibility,
    geometry_validate,
    impact,
    observe,
    options,
    policy,
    route,
    verify,
)
from civicripple.services.audit import AuditTrail
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.routing import ReplayRoutingProvider
from civicripple.services.storage import InMemoryIncidentStore


def _ctx(invocation_state: dict) -> IncidentContext | None:
    return invocation_state.get(CONTEXT_KEY)


def extract_succeeded(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.failure != "EXTRACTION_FAILED" and ctx.candidate is not None


def extract_failed(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.failure == "EXTRACTION_FAILED"


def verified(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.verdict is not None and ctx.verdict.status is VerificationStatus.VERIFIED


def unverified(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.failure == "UNVERIFIED_SOURCE"


def impact_affected(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.impact is not None and bool(ctx.impact.affected_route_ids)


def impact_none(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.impact is not None and not ctx.impact.affected_route_ids


def candidate_present(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.route_candidate is not None


def candidate_missing(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return ctx is not None and ctx.route_candidate is None and ctx.failure == "ROUTING_UNAVAILABLE"


def candidate_clear(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return (
        ctx is not None
        and ctx.route_candidate is not None
        and ctx.route_candidate.independently_clear_of_disruption
    )


def candidate_unsafe(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return (
        ctx is not None
        and ctx.route_candidate is not None
        and not ctx.route_candidate.independently_clear_of_disruption
    )


def decision_auto(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return (
        ctx is not None
        and ctx.decision is not None
        and ctx.decision.classification is DecisionClassification.AUTO_RESOLVABLE
    )


def decision_human(state, *, invocation_state, **kwargs) -> bool:
    ctx = _ctx(invocation_state)
    return (
        ctx is not None
        and ctx.decision is not None
        and ctx.decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    )


def build_incident_graph(
    *,
    extractor: Agent,
    verifier: Agent,
    options_agent: Agent,
    source: ReplayCivicSource,
    routing: ReplayRoutingProvider,
    trail: AuditTrail,
    store: InMemoryIncidentStore,
) -> Graph:
    builder = GraphBuilder()
    builder.add_node(observe.make_observe_node(source, trail), "observe")
    builder.add_node(extract.make_extract_node(extractor, trail), "extract")
    builder.add_node(verify.make_verify_node(verifier, trail), "verify")
    builder.add_node(impact.make_impact_node(trail), "impact")
    builder.add_node(route.make_route_node(routing, trail), "route")
    builder.add_node(geometry_validate.make_geometry_validate_node(trail), "geometry_validate")
    builder.add_node(feasibility.make_feasibility_node(trail), "feasibility")
    builder.add_node(policy.make_policy_node(trail), "policy")
    builder.add_node(options.make_options_node(options_agent, trail), "options")
    builder.add_node(audit.make_audit_node(trail, store), "audit")

    builder.add_edge("observe", "extract")
    builder.add_edge("extract", "verify", condition=extract_succeeded)
    builder.add_edge("extract", "audit", condition=extract_failed)
    builder.add_edge("verify", "impact", condition=verified)
    builder.add_edge("verify", "audit", condition=unverified)
    builder.add_edge("impact", "route", condition=impact_affected)
    builder.add_edge("impact", "audit", condition=impact_none)
    builder.add_edge("route", "geometry_validate", condition=candidate_present)
    builder.add_edge("route", "policy", condition=candidate_missing)
    builder.add_edge("geometry_validate", "feasibility", condition=candidate_clear)
    builder.add_edge("geometry_validate", "policy", condition=candidate_unsafe)
    builder.add_edge("feasibility", "policy")
    builder.add_edge("policy", "audit", condition=decision_auto)
    builder.add_edge("policy", "options", condition=decision_human)
    builder.add_edge("options", "audit")

    builder.set_entry_point("observe")
    builder.set_execution_timeout(300)
    builder.set_node_timeout(60)
    # Total executions across the whole graph (runaway guard), NOT per-node:
    # one incident traverses up to 9 nodes.
    builder.set_max_node_executions(20)
    return builder.build()
