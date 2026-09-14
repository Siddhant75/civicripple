import pytest

from civicripple.domain.enums import IncidentState
from civicripple.domain.errors import InvalidStateTransition
from civicripple.orchestration.state import transition


def test_valid_path_to_resolved_via_no_impact() -> None:
    state = transition(IncidentState.DETECTED, IncidentState.EXTRACTED)
    state = transition(state, IncidentState.VERIFIED)
    state = transition(state, IncidentState.IMPACT_ASSESSED)
    state = transition(state, IncidentState.NO_IMPACT)
    state = transition(state, IncidentState.RESOLVED)
    assert state is IncidentState.RESOLVED


def test_valid_path_to_resolved_via_auto_approved() -> None:
    state = transition(IncidentState.DETECTED, IncidentState.EXTRACTED)
    state = transition(state, IncidentState.VERIFIED)
    state = transition(state, IncidentState.IMPACT_ASSESSED)
    state = transition(state, IncidentState.ROUTE_REQUESTED)
    state = transition(state, IncidentState.CANDIDATE_VALIDATED)
    state = transition(state, IncidentState.FEASIBLE)
    state = transition(state, IncidentState.POLICY_EVALUATED)
    state = transition(state, IncidentState.AUTO_APPROVED)
    state = transition(state, IncidentState.RESOLVED)
    assert state is IncidentState.RESOLVED


def test_valid_path_to_review_required_via_infeasible() -> None:
    state = transition(IncidentState.DETECTED, IncidentState.EXTRACTED)
    state = transition(state, IncidentState.VERIFIED)
    state = transition(state, IncidentState.IMPACT_ASSESSED)
    state = transition(state, IncidentState.ROUTE_REQUESTED)
    state = transition(state, IncidentState.CANDIDATE_VALIDATED)
    state = transition(state, IncidentState.INFEASIBLE)
    state = transition(state, IncidentState.REVIEW_REQUIRED)
    assert state is IncidentState.REVIEW_REQUIRED


def test_valid_early_escalation_to_review_required() -> None:
    state = transition(IncidentState.DETECTED, IncidentState.REVIEW_REQUIRED)
    assert state is IncidentState.REVIEW_REQUIRED


def test_candidate_rejection_routes_to_review_required() -> None:
    state = transition(IncidentState.ROUTE_REQUESTED, IncidentState.CANDIDATE_REJECTED)
    state = transition(state, IncidentState.REVIEW_REQUIRED)
    assert state is IncidentState.REVIEW_REQUIRED


def test_human_decisions_from_review_required() -> None:
    assert (
        transition(IncidentState.REVIEW_REQUIRED, IncidentState.HUMAN_APPROVED)
        is IncidentState.HUMAN_APPROVED
    )
    assert (
        transition(IncidentState.REVIEW_REQUIRED, IncidentState.HUMAN_REJECTED)
        is IncidentState.HUMAN_REJECTED
    )
    assert transition(IncidentState.HUMAN_APPROVED, IncidentState.RESOLVED) is IncidentState.RESOLVED
    assert transition(IncidentState.HUMAN_REJECTED, IncidentState.OPEN) is IncidentState.OPEN


def test_detected_to_resolved_is_invalid() -> None:
    with pytest.raises(InvalidStateTransition):
        transition(IncidentState.DETECTED, IncidentState.RESOLVED)


def test_review_required_to_auto_approved_is_invalid() -> None:
    with pytest.raises(InvalidStateTransition):
        transition(IncidentState.REVIEW_REQUIRED, IncidentState.AUTO_APPROVED)


def test_resolved_to_open_is_invalid() -> None:
    with pytest.raises(InvalidStateTransition):
        transition(IncidentState.RESOLVED, IncidentState.OPEN)


def test_error_exposes_current_and_target() -> None:
    with pytest.raises(InvalidStateTransition) as excinfo:
        transition(IncidentState.RESOLVED, IncidentState.OPEN)
    assert excinfo.value.current is IncidentState.RESOLVED
    assert excinfo.value.target is IncidentState.OPEN
