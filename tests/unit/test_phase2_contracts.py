from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from civicripple.domain.enums import IncidentState, VerificationStatus
from civicripple.domain.models import (
    AuditEvent,
    BoundedOption,
    DisruptionEvent,
    DisruptionEventCandidate,
    IncidentRecord,
    OptionsReport,
    VerificationVerdict,
)


def _candidate_kwargs() -> dict:
    return {
        "event_id": "evt-1",
        "type": "ROAD_CLOSURE",
        "authority": "City of Replayville",
        "source_url": "https://replay.example/1",
        "published_at": datetime(2026, 9, 3, 7, 30, tzinfo=timezone.utc),
        "valid_from": datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        "valid_until": datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
        "geometry": {
            "kind": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
        },
        "severity": "HIGH",
        "facts": [],
        "verification_status": "UNVERIFIED",
    }


def test_candidate_is_schema_bound_and_promotes_to_event() -> None:
    candidate = DisruptionEventCandidate.model_validate(_candidate_kwargs())
    event = DisruptionEvent.model_validate(candidate.model_dump())
    assert event.event_id == candidate.event_id


def test_candidate_rejects_invalid_geometry_kind() -> None:
    kwargs = _candidate_kwargs()
    kwargs["geometry"] = {"kind": "MultiPolygon", "coordinates": [[[[0.0, 0.0]]]]}
    with pytest.raises(ValidationError):
        DisruptionEventCandidate.model_validate(kwargs)


def test_verification_verdict_roundtrip() -> None:
    verdict = VerificationVerdict(
        status=VerificationStatus.VERIFIED,
        authority="City of Replayville",
        reasons=["official source"],
    )
    assert verdict.status is VerificationStatus.VERIFIED


def test_options_report_holds_bounded_options() -> None:
    report = OptionsReport(
        incident_id="incident-1",
        affected_stop_ids=["stop-b2"],
        summary="One stop at risk",
        options=[
            BoundedOption(
                option_id="opt-1",
                title="Approve delayed reroute",
                description="Arrives 7 minutes late; requires coordinator approval",
                requires_human_approval=True,
            )
        ],
    )
    assert report.options[0].requires_human_approval is True


def test_audit_event_stores_structured_facts_only() -> None:
    event = AuditEvent(
        event_id="audit-1",
        correlation_id="incident-1",
        node="impact",
        state_from=IncidentState.VERIFIED,
        state_to=IncidentState.IMPACT_ASSESSED,
        facts={"affected_leg_ids": ["leg-b2"], "spatial_overlap": True},
        mode="local_replay",
        recorded_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )
    assert event.facts["spatial_overlap"] is True


def test_incident_record_defaults() -> None:
    record = IncidentRecord(
        correlation_id="incident-1",
        state=IncidentState.REVIEW_REQUIRED,
        decision=None,
        review_payload=None,
        options=None,
        created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )
    assert record.state is IncidentState.REVIEW_REQUIRED
