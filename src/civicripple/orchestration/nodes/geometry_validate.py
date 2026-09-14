from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.geometry import validate_route_candidate


def run(ctx: IncidentContext, trail: AuditTrail) -> IncidentContext:
    if ctx.route_candidate is None or ctx.disruption is None:
        raise RuntimeError("geometry_validate: route candidate and disruption required")
    validated = validate_route_candidate(ctx.route_candidate, ctx.disruption)
    target = (
        IncidentState.CANDIDATE_VALIDATED
        if validated.independently_clear_of_disruption
        else IncidentState.CANDIDATE_REJECTED
    )
    audit_transition(
        trail,
        ctx.correlation_id,
        "geometry_validate",
        IncidentState.ROUTE_REQUESTED,
        target,
        {
            "independently_clear": validated.independently_clear_of_disruption,
            "provider_notices": validated.provider_notices,
        },
        ctx.mode,
    )
    return ctx.model_copy(update={"route_candidate": validated, "state": target})


def make_geometry_validate_node(trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("geometry_validate", lambda ctx: run(ctx, trail))
