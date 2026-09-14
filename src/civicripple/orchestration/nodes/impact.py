from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.geometry import assess_impact


def run(ctx: IncidentContext, trail: AuditTrail) -> IncidentContext:
    if ctx.disruption is None or ctx.plan is None:
        raise RuntimeError("impact: disruption and plan must be present")
    impact = assess_impact(ctx.disruption, ctx.plan)
    audit_transition(
        trail,
        ctx.correlation_id,
        "impact",
        IncidentState.VERIFIED,
        IncidentState.IMPACT_ASSESSED,
        {
            "affected_route_ids": impact.affected_route_ids,
            "affected_leg_ids": impact.affected_leg_ids,
        },
        ctx.mode,
    )
    ctx = ctx.model_copy(update={"impact": impact, "state": IncidentState.IMPACT_ASSESSED})
    if not impact.affected_leg_ids:
        audit_transition(
            trail,
            ctx.correlation_id,
            "impact",
            IncidentState.IMPACT_ASSESSED,
            IncidentState.NO_IMPACT,
            {"affected_leg_ids": []},
            ctx.mode,
        )
        return ctx.model_copy(update={"state": IncidentState.NO_IMPACT})
    return ctx


def make_impact_node(trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("impact", lambda ctx: run(ctx, trail))
