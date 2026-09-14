"""Incident state machine.

Encodes the frozen state machine from docs/architecture.md section 7 as an
explicit adjacency map. Transitions are never inferred from enum ordering.
"""

from civicripple.domain.enums import IncidentState
from civicripple.domain.errors import InvalidStateTransition

_ALLOWED_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    IncidentState.DETECTED: frozenset(
        {IncidentState.EXTRACTED, IncidentState.REVIEW_REQUIRED}
    ),
    IncidentState.EXTRACTED: frozenset({IncidentState.VERIFIED}),
    IncidentState.VERIFIED: frozenset({IncidentState.IMPACT_ASSESSED}),
    IncidentState.IMPACT_ASSESSED: frozenset(
        {IncidentState.NO_IMPACT, IncidentState.ROUTE_REQUESTED}
    ),
    IncidentState.NO_IMPACT: frozenset({IncidentState.RESOLVED}),
    IncidentState.ROUTE_REQUESTED: frozenset(
        {IncidentState.CANDIDATE_REJECTED, IncidentState.CANDIDATE_VALIDATED}
    ),
    IncidentState.CANDIDATE_REJECTED: frozenset({IncidentState.REVIEW_REQUIRED}),
    IncidentState.CANDIDATE_VALIDATED: frozenset(
        {IncidentState.FEASIBLE, IncidentState.INFEASIBLE}
    ),
    IncidentState.FEASIBLE: frozenset({IncidentState.POLICY_EVALUATED}),
    IncidentState.INFEASIBLE: frozenset({IncidentState.REVIEW_REQUIRED}),
    IncidentState.POLICY_EVALUATED: frozenset(
        {IncidentState.AUTO_APPROVED, IncidentState.REVIEW_REQUIRED}
    ),
    IncidentState.AUTO_APPROVED: frozenset({IncidentState.RESOLVED}),
    IncidentState.REVIEW_REQUIRED: frozenset(
        {IncidentState.HUMAN_APPROVED, IncidentState.HUMAN_REJECTED}
    ),
    IncidentState.HUMAN_APPROVED: frozenset({IncidentState.RESOLVED}),
    IncidentState.HUMAN_REJECTED: frozenset({IncidentState.OPEN}),
    IncidentState.RESOLVED: frozenset(),
    IncidentState.OPEN: frozenset(),
}


def transition(current: IncidentState, target: IncidentState) -> IncidentState:
    """Validate a state transition and return the target state.

    Raises InvalidStateTransition when the adjacency map does not allow it.
    """
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(current, target)
    return target
