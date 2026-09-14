from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.routing import ReplayRoutingProvider


def run(ctx: IncidentContext, routing: ReplayRoutingProvider, trail: AuditTrail) -> IncidentContext:
    if ctx.impact is None or not ctx.impact.affected_route_ids:
        raise RuntimeError("route: impact must have affected routes")
    route_id = ctx.impact.affected_route_ids[0]  # single-route MVP
    route = next(r for r in ctx.plan.routes if r.route_id == route_id)
    audit_transition(
        trail,
        ctx.correlation_id,
        "route",
        IncidentState.IMPACT_ASSESSED,
        IncidentState.ROUTE_REQUESTED,
        {"requested_route_id": route_id},
        ctx.mode,
    )
    try:
        candidate = routing.request_candidate(ctx.plan, route, ctx.disruption)
    except Exception as exc:  # explicit adapter-boundary handling: provider
        # unavailable -> no candidate, never an invented route (fail closed)
        audit_transition(
            trail,
            ctx.correlation_id,
            "route",
            IncidentState.ROUTE_REQUESTED,
            IncidentState.ROUTE_REQUESTED,
            {"provider_error": str(exc), "failure": "ROUTING_UNAVAILABLE"},
            ctx.mode,
        )
        return ctx.model_copy(
            update={"state": IncidentState.ROUTE_REQUESTED, "failure": "ROUTING_UNAVAILABLE"}
        )
    audit_transition(
        trail,
        ctx.correlation_id,
        "route",
        IncidentState.ROUTE_REQUESTED,
        IncidentState.ROUTE_REQUESTED,
        {"candidate_provider": candidate.provider, "candidate_duration_s": candidate.duration_s},
        ctx.mode,
    )
    return ctx.model_copy(
        update={"route_candidate": candidate, "state": IncidentState.ROUTE_REQUESTED}
    )


def make_route_node(routing: ReplayRoutingProvider, trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("route", lambda ctx: run(ctx, routing, trail))
