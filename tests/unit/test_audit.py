from datetime import datetime, timezone

import pytest

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import AuditEvent
from civicripple.services.audit import AuditTrail, audit_transition


def _event(correlation_id: str = "incident-1", seq: int = 1) -> AuditEvent:
    return AuditEvent(
        event_id=f"audit-{seq}",
        correlation_id=correlation_id,
        node="impact",
        state_from=IncidentState.VERIFIED,
        state_to=IncidentState.IMPACT_ASSESSED,
        facts={"affected_leg_ids": ["leg-b2"]},
        mode="local_replay",
        recorded_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )


def test_audit_trail_is_append_only_in_order() -> None:
    trail = AuditTrail()
    first = audit_transition(
        trail, "incident-1", "impact",
        IncidentState.VERIFIED, IncidentState.IMPACT_ASSESSED, {}, "local_replay",
    )
    second = audit_transition(
        trail, "incident-1", "impact",
        IncidentState.IMPACT_ASSESSED, IncidentState.ROUTE_REQUESTED, {}, "local_replay",
    )
    events = trail.events_for("incident-1")
    assert [e.state_to for e in events] == [
        IncidentState.IMPACT_ASSESSED,
        IncidentState.ROUTE_REQUESTED,
    ]
    assert events[0].recorded_at <= events[1].recorded_at
    assert first.event_id != second.event_id


def test_events_filtered_by_correlation_id() -> None:
    trail = AuditTrail()
    audit_transition(
        trail, "incident-a", "observe",
        IncidentState.DETECTED, IncidentState.DETECTED, {}, "local_replay",
    )
    audit_transition(
        trail, "incident-b", "observe",
        IncidentState.DETECTED, IncidentState.DETECTED, {}, "local_replay",
    )
    assert len(trail.events_for("incident-a")) == 1
    assert len(trail.all_events()) == 2


def test_record_rejects_duplicate_event_id() -> None:
    trail = AuditTrail()
    event = _event()
    trail.record(event)
    with pytest.raises(ValueError):
        trail.record(event)


def test_audit_transition_fails_closed_on_unpersisted_write() -> None:
    class FailingTrail(AuditTrail):
        def record(self, event: AuditEvent) -> None:
            raise OSError("storage unavailable")

    with pytest.raises(OSError):
        audit_transition(
            FailingTrail(), "incident-1", "impact",
            IncidentState.VERIFIED, IncidentState.IMPACT_ASSESSED, {}, "local_replay",
        )
