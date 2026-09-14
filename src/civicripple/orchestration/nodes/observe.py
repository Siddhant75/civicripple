from civicripple.domain.enums import IncidentState
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.civic_source import ReplayCivicSource


def run(ctx: IncidentContext, source: ReplayCivicSource, trail: AuditTrail) -> IncidentContext:
    # The plan always loads from the fixture; a notice text already supplied
    # by the caller (live watch items) is never overwritten by fixture text.
    updates = {"plan": source.load_plan()}
    if ctx.notice_text is None:
        updates["notice_text"] = source.load_notice_text()
    ctx = ctx.model_copy(update=updates)
    audit_transition(
        trail,
        ctx.correlation_id,
        "observe",
        IncidentState.DETECTED,
        IncidentState.DETECTED,
        {"notice_loaded": True, "plan_loaded": True},
        ctx.mode,
    )
    return ctx


def make_observe_node(source: ReplayCivicSource, trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("observe", lambda ctx: run(ctx, source, trail))
