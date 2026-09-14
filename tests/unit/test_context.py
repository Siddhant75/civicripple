from datetime import datetime, timezone

import pytest

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import IncidentRecord
from civicripple.orchestration.context import (
    CONTEXT_KEY,
    IncidentContext,
    get_context,
    put_context,
)
from civicripple.services.storage import InMemoryIncidentStore


def test_context_defaults_to_detected_state() -> None:
    ctx = IncidentContext(correlation_id="incident-1", mode="local_replay")
    assert ctx.state is IncidentState.DETECTED
    assert ctx.plan is None and ctx.disruption is None


def test_put_and_get_context_roundtrip() -> None:
    state: dict = {}
    ctx = IncidentContext(correlation_id="incident-1", mode="local_replay")
    put_context(state, ctx)
    assert state[CONTEXT_KEY] is ctx
    assert get_context(state).correlation_id == "incident-1"


def test_get_context_raises_when_missing() -> None:
    with pytest.raises(RuntimeError):
        get_context({})


def test_incident_store_save_and_get() -> None:
    store = InMemoryIncidentStore()
    record = IncidentRecord(
        correlation_id="incident-1",
        state=IncidentState.REVIEW_REQUIRED,
        created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
    )
    store.save(record)
    assert store.get("incident-1") == record
    assert store.get("missing") is None


def test_in_memory_store_lists_all_records() -> None:
    store = InMemoryIncidentStore()
    for corr in ("a", "b"):
        store.save(
            IncidentRecord(
                correlation_id=corr,
                state=IncidentState.RESOLVED,
                created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
            )
        )
    assert [r.correlation_id for r in store.list()] == ["a", "b"]


def test_dynamodb_store_lists_incident_rows_only() -> None:
    from civicripple.services.storage import DynamoDbIncidentStore
    from test_dynamodb_adapters import FakeTable

    table = FakeTable()
    store = DynamoDbIncidentStore(table)
    for corr in ("a", "b"):
        store.save(
            IncidentRecord(
                correlation_id=corr,
                state=IncidentState.RESOLVED,
                created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
            )
        )
    # An audit row shares the pk; list() must return only INCIDENT rows.
    table.put_item(Item={"pk": "a", "sk": "AUDIT#audit-x", "facts_json": "{}"})
    assert [r.correlation_id for r in store.list()] == ["a", "b"]
