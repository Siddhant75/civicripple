from datetime import UTC, datetime

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import (
    IncidentRecord,
    MapLeg,
    MapSnapshot,
    MapStop,
    WhatIfContext,
)
from civicripple.domain.policies import build_human_review_payload, classify_incident
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.storage import InMemoryIncidentStore


def _build_map_snapshot(ctx: IncidentContext) -> MapSnapshot | None:
    """Deterministic map data for the dashboard, from ctx at audit time."""
    if ctx.plan is None:
        return None
    affected = set(ctx.impact.affected_leg_ids) if ctx.impact else set()
    planned_by_stop = {
        leg.to_stop_id: leg.planned_arrival
        for route in ctx.plan.routes
        for leg in route.legs
    }
    projected = (
        {a.stop_id: a.arrival_at for a in ctx.feasibility.stop_arrivals}
        if ctx.feasibility
        else {}
    )
    stops = [
        MapStop(
            stop_id=stop.stop_id,
            location=stop.location,
            window_start=stop.time_window.start,
            window_end=stop.time_window.end,
            planned_arrival=planned_by_stop.get(stop.stop_id),
            projected_arrival=projected.get(stop.stop_id),
        )
        for route in ctx.plan.routes
        for stop in route.stops
    ]
    legs = [
        MapLeg(
            leg_id=leg.leg_id,
            route_id=route.route_id,
            coordinates=leg.geometry.coordinates if leg.geometry.kind == "LineString" else [],
            affected=leg.leg_id in affected,
        )
        for route in ctx.plan.routes
        for leg in route.legs
    ]
    return MapSnapshot(
        depot=ctx.plan.depot,
        stops=stops,
        legs=legs,
        disruption_geometry=ctx.disruption.geometry if ctx.disruption else None,
        candidate_geometry=ctx.route_candidate.geometry if ctx.route_candidate else None,
        candidate_duration_s=ctx.route_candidate.duration_s if ctx.route_candidate else None,
    )


def run(ctx: IncidentContext, trail: AuditTrail, store: InMemoryIncidentStore) -> IncidentContext:
    decision = ctx.decision
    if decision is None and ctx.impact is not None:
        decision = classify_incident(ctx.impact, ctx.route_candidate, ctx.feasibility)
    if ctx.state is IncidentState.NO_IMPACT:
        audit_transition(
            trail,
            ctx.correlation_id,
            "audit",
            IncidentState.NO_IMPACT,
            IncidentState.RESOLVED,
            {"classification": decision.classification.value},
            ctx.mode,
        )
        state = IncidentState.RESOLVED
        review_payload = None
    elif ctx.state is IncidentState.AUTO_APPROVED:
        audit_transition(
            trail,
            ctx.correlation_id,
            "audit",
            IncidentState.AUTO_APPROVED,
            IncidentState.RESOLVED,
            {"permitted_action": decision.permitted_action or ""},
            ctx.mode,
        )
        state = IncidentState.RESOLVED
        review_payload = None
    elif ctx.state is IncidentState.REVIEW_REQUIRED:
        # Human-required: remain pending. Silence is never approval.
        audit_transition(
            trail,
            ctx.correlation_id,
            "audit",
            IncidentState.REVIEW_REQUIRED,
            IncidentState.REVIEW_REQUIRED,
            {
                "reason": (decision.review_reason if decision else "") or ctx.failure or "",
                "pending_human": True,
            },
            ctx.mode,
        )
        state = IncidentState.REVIEW_REQUIRED
        if decision is not None and ctx.impact is not None:
            review_payload = build_human_review_payload(
                ctx.correlation_id, ctx.impact, ctx.feasibility, decision.review_reason or ""
            )
        else:
            # Early escalation (extraction failure / unverified source):
            # no deterministic impact exists, so no payload can be built.
            review_payload = None
    else:
        raise RuntimeError(f"audit: unexpected terminal state {ctx.state}")
    whatif_context = None
    if (
        ctx.impact is not None
        and ctx.impact.affected_route_ids
        and ctx.route_candidate is not None
        and ctx.plan is not None
    ):
        whatif_context = WhatIfContext(
            plan=ctx.plan,
            route_id=ctx.impact.affected_route_ids[0],
            candidate=ctx.route_candidate,
        )
    now = datetime.now(UTC)
    store.save(
        IncidentRecord(
            correlation_id=ctx.correlation_id,
            state=state,
            decision=decision,
            review_payload=review_payload,
            options=ctx.options,
            map=_build_map_snapshot(ctx),
            whatif_context=whatif_context,
            created_at=now,
            updated_at=now,
        )
    )
    return ctx.model_copy(update={"decision": decision, "state": state})


def make_audit_node(trail: AuditTrail, store: InMemoryIncidentStore) -> DeterministicNode:
    return DeterministicNode("audit", lambda ctx: run(ctx, trail, store))
