from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import AuditEvent, IncidentRecord
from civicripple.services.audit import DynamoDbAuditTrail
from civicripple.services.storage import DynamoDbIncidentStore


class FakeTable:
    """Resource-style Table double: in-memory items, real call shapes."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.puts: list[dict] = []
        self.queries: list[dict] = []
        self.fail_on_put = False

    def put_item(self, *, Item, ConditionExpression=None, **kwargs):
        if self.fail_on_put:
            raise ClientError(
                {"Error": {"Code": "InternalServerException", "Message": "down"}},
                "PutItem",
            )
        self.puts.append({"Item": Item, "ConditionExpression": ConditionExpression})
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "dup"}},
                "PutItem",
            )
        self.items[key] = Item

    def query(self, **kwargs):
        self.queries.append(kwargs)
        # This codebase always queries pk = :c AND begins_with(sk, :p).
        correlation_id = kwargs["ExpressionAttributeValues"][":c"]
        prefix = kwargs["ExpressionAttributeValues"][":p"]
        items = [
            item
            for (pk, sk), item in sorted(self.items.items())
            if pk == correlation_id and sk.startswith(prefix)
        ]
        if kwargs.get("ScanIndexForward") is False:
            items = list(reversed(items))
        return {"Items": items}

    def get_item(self, *, Key, ConsistentRead=None, **kwargs):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def scan(self, **kwargs):
        return {"Items": list(self.items.values())}


def _event(correlation_id: str = "incident-1", seq: int = 1) -> AuditEvent:
    return AuditEvent(
        event_id=f"audit-{seq}",
        correlation_id=correlation_id,
        node="impact",
        state_from=IncidentState.VERIFIED,
        state_to=IncidentState.IMPACT_ASSESSED,
        facts={"affected_leg_ids": ["leg-b2"], "spatial_overlap": True},
        mode="aws",
        recorded_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )


def test_audit_record_writes_append_only_item() -> None:
    table = FakeTable()
    trail = DynamoDbAuditTrail(table)
    event = _event()
    trail.record(event)
    assert table.puts[0]["ConditionExpression"] == "attribute_not_exists(sk)"
    stored = table.items[("incident-1", "AUDIT#audit-1")]
    assert stored["node"] == "impact"
    assert '"spatial_overlap":true' in stored["facts_json"]


def test_audit_record_rejects_duplicate() -> None:
    table = FakeTable()
    trail = DynamoDbAuditTrail(table)
    trail.record(_event())
    with pytest.raises(ValueError):
        trail.record(_event())


def test_audit_record_fails_closed_on_client_error() -> None:
    table = FakeTable()
    table.fail_on_put = True
    trail = DynamoDbAuditTrail(table)
    with pytest.raises(ClientError):
        trail.record(_event())


def test_events_for_roundtrips_events() -> None:
    table = FakeTable()
    trail = DynamoDbAuditTrail(table)
    first = _event(seq=1)
    second = _event(seq=2)
    trail.record(first)
    trail.record(second)
    events = trail.events_for("incident-1")
    assert [e.event_id for e in events] == ["audit-1", "audit-2"]
    assert events[0].facts == first.facts
    assert events[0].mode == "aws"


def test_all_events_scans() -> None:
    table = FakeTable()
    trail = DynamoDbAuditTrail(table)
    trail.record(_event(correlation_id="a", seq=1))
    trail.record(_event(correlation_id="b", seq=2))
    assert len(trail.all_events()) == 2


def test_incident_store_save_and_get() -> None:
    table = FakeTable()
    store = DynamoDbIncidentStore(table)
    record = IncidentRecord(
        correlation_id="incident-1",
        state=IncidentState.REVIEW_REQUIRED,
        created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )
    store.save(record)
    assert store.get("incident-1") == record
    assert store.get("missing") is None
