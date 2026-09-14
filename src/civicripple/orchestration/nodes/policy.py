from civicripple.domain.enums import DecisionClassification, IncidentState
from civicripple.domain.policies import classify_incident
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition


def run(ctx: IncidentContext, trail: AuditTrail) -> IncidentContext:
    if ctx.impact is None:
        raise RuntimeError("policy: impact required")
    decision = classify_incident(ctx.impact, ctx.route_candidate, ctx.feasibility)
    if ctx.state is IncidentState.ROUTE_REQUESTED:
        # No candidate returned; policy says ROUTING_UNAVAILABLE.
        audit_transition(
            trail,
            ctx.correlation_id,
            "policy",
            IncidentState.ROUTE_REQUESTED,
            IncidentState.CANDIDATE_REJECTED,
            {"reason": decision.review_reason or ""},
            ctx.mode,
        )
        audit_transition(
            trail,
            ctx.correlation_id,
            "policy",
            IncidentState.CANDIDATE_REJECTED,
            IncidentState.REVIEW_REQUIRED,
            {"reason": decision.review_reason or ""},
            ctx.mode,
        )
        return ctx.model_copy(update={"decision": decision, "state": IncidentState.REVIEW_REQUIRED})
    if ctx.state is IncidentState.CANDIDATE_REJECTED:
        audit_transition(
            trail,
            ctx.correlation_id,
            "policy",
            IncidentState.CANDIDATE_REJECTED,
            IncidentState.REVIEW_REQUIRED,
            {"reason": decision.review_reason or ""},
            ctx.mode,
        )
        return ctx.model_copy(update={"decision": decision, "state": IncidentState.REVIEW_REQUIRED})
    if ctx.state not in (IncidentState.FEASIBLE, IncidentState.INFEASIBLE):
        raise RuntimeError(f"policy: unexpected state {ctx.state}")
    audit_transition(
        trail,
        ctx.correlation_id,
        "policy",
        ctx.state,
        IncidentState.POLICY_EVALUATED,
        {"classification": decision.classification.value},
        ctx.mode,
    )
    if decision.classification is DecisionClassification.AUTO_RESOLVABLE:
        audit_transition(
            trail,
            ctx.correlation_id,
            "policy",
            IncidentState.POLICY_EVALUATED,
            IncidentState.AUTO_APPROVED,
            {"permitted_action": decision.permitted_action or ""},
            ctx.mode,
        )
        return ctx.model_copy(update={"decision": decision, "state": IncidentState.AUTO_APPROVED})
    audit_transition(
        trail,
        ctx.correlation_id,
        "policy",
        IncidentState.POLICY_EVALUATED,
        IncidentState.REVIEW_REQUIRED,
        {"reason": decision.review_reason or ""},
        ctx.mode,
    )
    return ctx.model_copy(update={"decision": decision, "state": IncidentState.REVIEW_REQUIRED})


def make_policy_node(trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("policy", lambda ctx: run(ctx, trail))
