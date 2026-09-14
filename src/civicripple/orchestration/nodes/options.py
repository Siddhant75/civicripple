from strands import Agent

from civicripple.agents.options_agent import explain_options, options_match_impact
from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition


def run(ctx: IncidentContext, options_agent: Agent, trail: AuditTrail) -> IncidentContext:
    if ctx.decision is None or ctx.impact is None:
        raise RuntimeError("options: decision and impact required")
    report = explain_options(
        options_agent, ctx.correlation_id, ctx.decision, ctx.impact, ctx.feasibility
    )
    if not options_match_impact(report, ctx.impact):
        # Options invented or dropped affected stops: fail closed, stay pending.
        audit_transition(
            trail,
            ctx.correlation_id,
            "options",
            IncidentState.REVIEW_REQUIRED,
            IncidentState.REVIEW_REQUIRED,
            {"failure": "OPTIONS_MISMATCH"},
            ctx.mode,
        )
        return ctx.model_copy(update={"failure": "OPTIONS_MISMATCH"})
    audit_transition(
        trail,
        ctx.correlation_id,
        "options",
        IncidentState.REVIEW_REQUIRED,
        IncidentState.REVIEW_REQUIRED,
        {"options_count": len(report.options)},
        ctx.mode,
    )
    return ctx.model_copy(update={"options": report})


def make_options_node(options_agent: Agent, trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("options", lambda ctx: run(ctx, options_agent, trail))
