from strands import Agent

from civicripple.agents.evidence_verifier import verify_evidence
from civicripple.domain.enums import IncidentState, VerificationStatus
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition


def run(ctx: IncidentContext, verifier: Agent, trail: AuditTrail) -> IncidentContext:
    if ctx.candidate is None:
        raise RuntimeError("verify: extract must run first (candidate missing)")
    verdict = verify_evidence(verifier, ctx.candidate)
    if verdict.status is VerificationStatus.VERIFIED:
        audit_transition(
            trail,
            ctx.correlation_id,
            "verify",
            IncidentState.EXTRACTED,
            IncidentState.VERIFIED,
            {"authority": verdict.authority},
            ctx.mode,
        )
        return ctx.model_copy(update={"verdict": verdict, "state": IncidentState.VERIFIED})
    audit_transition(
        trail,
        ctx.correlation_id,
        "verify",
        IncidentState.EXTRACTED,
        IncidentState.REVIEW_REQUIRED,
        {"failure": "UNVERIFIED_SOURCE", "reasons": verdict.reasons},
        ctx.mode,
    )
    return ctx.model_copy(
        update={
            "verdict": verdict,
            "state": IncidentState.REVIEW_REQUIRED,
            "failure": "UNVERIFIED_SOURCE",
        }
    )


def make_verify_node(verifier: Agent, trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("verify", lambda ctx: run(ctx, verifier, trail))
