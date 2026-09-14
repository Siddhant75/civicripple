"""Typed incident context carried through the orchestration graph.

The graph passes only text between nodes; the shared mutable
invocation_state dict is the typed data channel. Conditional edges are
predicates over this context — never string matching.
"""

from pydantic import BaseModel

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import (
    DisruptionEvent,
    DisruptionEventCandidate,
    FeasibilityResult,
    ImpactAssessment,
    IncidentDecision,
    OperationPlan,
    OptionsReport,
    RouteCandidate,
    VerificationVerdict,
)

CONTEXT_KEY = "civicripple_context"


class IncidentContext(BaseModel):
    correlation_id: str
    state: IncidentState = IncidentState.DETECTED
    mode: str
    notice_text: str | None = None
    source_url: str | None = None
    plan: OperationPlan | None = None
    candidate: DisruptionEventCandidate | None = None
    disruption: DisruptionEvent | None = None
    verdict: VerificationVerdict | None = None
    impact: ImpactAssessment | None = None
    route_candidate: RouteCandidate | None = None
    feasibility: FeasibilityResult | None = None
    decision: IncidentDecision | None = None
    options: OptionsReport | None = None
    failure: str | None = None
    geocode_first: bool = False


def get_context(invocation_state: dict) -> IncidentContext:
    ctx = invocation_state.get(CONTEXT_KEY)
    if ctx is None:
        raise RuntimeError(f"missing {CONTEXT_KEY} in invocation_state")
    return ctx


def put_context(invocation_state: dict, ctx: IncidentContext) -> None:
    invocation_state[CONTEXT_KEY] = ctx
