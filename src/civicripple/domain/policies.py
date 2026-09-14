"""Fail-closed incident policy engine.

Converts deterministic outcomes into one of the three MVP classifications.
Pure decision logic over typed results — no LLM, no prose generation.
"""

from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import (
    FeasibilityResult,
    HumanReviewPayload,
    ImpactAssessment,
    IncidentDecision,
    RouteCandidate,
)

ROUTING_UNAVAILABLE = "ROUTING_UNAVAILABLE"
ROUTE_AVOIDANCE_UNPROVEN = "ROUTE_AVOIDANCE_UNPROVEN"
HARD_CONSTRAINT_VIOLATION = "HARD_CONSTRAINT_VIOLATION"
APPLY_INTERNAL_REROUTE = "APPLY_INTERNAL_REROUTE"


def classify_incident(
    impact: ImpactAssessment,
    candidate: RouteCandidate | None,
    feasibility: FeasibilityResult | None,
) -> IncidentDecision:
    """Apply the ordered fail-closed policy.

    Order matters: every human-required branch is checked before the
    auto-resolvable branch can fire.
    """
    # 1. No operational intersection.
    if not impact.affected_leg_ids:
        return IncidentDecision(classification=DecisionClassification.NO_IMPACT)

    # 2. Affected incident with no route candidate.
    if candidate is None:
        return IncidentDecision(
            classification=DecisionClassification.HUMAN_DECISION_REQUIRED,
            review_reason=ROUTING_UNAVAILABLE,
        )

    # 3. Candidate avoidance cannot be proven.
    if not candidate.independently_clear_of_disruption:
        return IncidentDecision(
            classification=DecisionClassification.HUMAN_DECISION_REQUIRED,
            review_reason=ROUTE_AVOIDANCE_UNPROVEN,
        )

    # 4. Hard delivery constraint violation.
    if feasibility is None or not feasibility.feasible:
        return IncidentDecision(
            classification=DecisionClassification.HUMAN_DECISION_REQUIRED,
            review_reason=HARD_CONSTRAINT_VIOLATION,
        )

    # 5. Safe candidate, feasible, policy-permitted.
    return IncidentDecision(
        classification=DecisionClassification.AUTO_RESOLVABLE,
        permitted_action=APPLY_INTERNAL_REROUTE,
    )


def build_human_review_payload(
    incident_id: str,
    impact: ImpactAssessment,
    feasibility: FeasibilityResult | None,
    reason: str,
) -> HumanReviewPayload:
    """Build the deterministic human-review payload.

    Contains only affected stop IDs, failed constraints, and the explicit
    policy reason — no generated explanatory prose.
    """
    violations = feasibility.violations if feasibility is not None else []
    return HumanReviewPayload(
        incident_id=incident_id,
        affected_stop_ids=impact.affected_stop_ids,
        failed_constraints=violations,
        reason=reason,
    )
