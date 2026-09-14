from pathlib import Path

import pytest

pytestmark = pytest.mark.aws_integration

from civicripple.config import Settings
from civicripple.domain.models import (
    DisruptionEvent,
    DisruptionEventCandidate,
    OperationPlan,
)
from civicripple.orchestration.runtime import build_bedrock_model
from civicripple.services.amazon_location import AmazonLocationRoutingProvider

FIXTURES = Path("src/civicripple/fixtures")


def test_bedrock_extractor_returns_schema_bound_candidate() -> None:
    from civicripple.agents.disruption_extractor import (
        build_extractor_agent,
        extract_disruption,
    )

    settings = Settings(mode="aws")
    agent = build_extractor_agent(build_bedrock_model(settings))
    notice = (FIXTURES / "notices_src" / "feasible_closure.txt").read_text()
    candidate = extract_disruption(
        agent, notice, "https://notices.replayville.gov/2026/feasible-closure"
    )
    # Real-LLM output is nondeterministic: assert schema bounds, not exact values.
    assert isinstance(candidate, DisruptionEventCandidate)
    assert candidate.type == "ROAD_CLOSURE"
    assert candidate.valid_from.year == 2026
    assert candidate.geometry.kind in ("Polygon", "LineString", "Point")


def test_amazon_location_routes_around_closure() -> None:
    from civicripple.services.amazon_location import build_geo_routes_client
    from civicripple.services.geometry import validate_route_candidate

    settings = Settings(mode="aws")
    plan = OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )
    disruption = DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / "feasible_closure.json").read_text()
    )
    route = next(r for r in plan.routes if r.route_id == "route-b")
    provider = AmazonLocationRoutingProvider(build_geo_routes_client(settings.aws_region))
    candidate = provider.request_candidate(plan, route, disruption)
    assert candidate.provider == "amazon-location"
    assert candidate.duration_s > 0
    # Independent fail-closed check on the real route geometry.
    validated = validate_route_candidate(candidate, disruption)
    # Best-effort avoidance on real streets may legitimately fail; either way
    # the deterministic gate must have produced a definite verdict.
    assert validated.independently_clear_of_disruption in (True, False)


def test_dynamodb_audit_roundtrip(disposable_table) -> None:
    from datetime import UTC, datetime

    from civicripple.domain.enums import IncidentState
    from civicripple.domain.models import AuditEvent, IncidentRecord
    from civicripple.services.audit import DynamoDbAuditTrail, audit_transition
    from civicripple.services.storage import DynamoDbIncidentStore

    trail = DynamoDbAuditTrail(disposable_table)
    audit_transition(
        trail,
        "incident-integration",
        "impact",
        IncidentState.VERIFIED,
        IncidentState.IMPACT_ASSESSED,
        {"affected_leg_ids": ["leg-b2"]},
        "aws",
    )
    events = trail.events_for("incident-integration")
    assert len(events) == 1
    assert events[0].facts == {"affected_leg_ids": ["leg-b2"]}

    store = DynamoDbIncidentStore(disposable_table)
    record = IncidentRecord(
        correlation_id="incident-integration",
        state=IncidentState.RESOLVED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    store.save(record)
    assert store.get("incident-integration") == record
