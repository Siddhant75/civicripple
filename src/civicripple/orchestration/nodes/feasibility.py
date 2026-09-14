from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.feasibility import evaluate_feasibility


def run(ctx: IncidentContext, trail: AuditTrail) -> IncidentContext:
    if ctx.route_candidate is None or ctx.impact is None or ctx.plan is None:
        raise RuntimeError("feasibility: candidate, impact, and plan required")
    route_id = ctx.impact.affected_route_ids[0]
    route = next(r for r in ctx.plan.routes if r.route_id == route_id)
    result = evaluate_feasibility(route, ctx.route_candidate)
    target = IncidentState.FEASIBLE if result.feasible else IncidentState.INFEASIBLE
    audit_transition(
        trail,
        ctx.correlation_id,
        "feasibility",
        IncidentState.CANDIDATE_VALIDATED,
        target,
        {"added_duration_s": result.added_duration_s, "violation_count": len(result.violations)},
        ctx.mode,
    )
    return ctx.model_copy(update={"feasibility": result, "state": target})


def make_feasibility_node(trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("feasibility", lambda ctx: run(ctx, trail))
