"""Append-only audit trail.

Every incident transition is recorded as a structured AuditEvent. Audit
persistence failure propagates (fail closed) — consequential actions must
never proceed un-audited.
"""

import json
import uuid
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from civicripple.domain.enums import IncidentState
from civicripple.domain.models import AuditEvent


class AuditTrail:
    """In-memory append-only trail (local replay). Phase 3 adds a DynamoDB
    implementation behind the same interface."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._event_ids: set[str] = set()

    def record(self, event: AuditEvent) -> None:
        if event.event_id in self._event_ids:
            raise ValueError(f"duplicate audit event id: {event.event_id}")
        self._event_ids.add(event.event_id)
        self._events.append(event)

    def events_for(self, correlation_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.correlation_id == correlation_id]

    def all_events(self) -> list[AuditEvent]:
        return list(self._events)


def audit_transition(
    trail: AuditTrail,
    correlation_id: str,
    node: str,
    state_from: IncidentState,
    state_to: IncidentState,
    facts: dict[str, str | int | bool | list[str]],
    mode: str,
) -> AuditEvent:
    event = AuditEvent(
        # Chronologically sortable id: DynamoDB sorts sk lexicographically,
        # so the audit query returns events in occurrence order. The uuid
        # suffix keeps ids unique (and duplicate-guarded) on collision.
        event_id=(
            f"audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        ),
        correlation_id=correlation_id,
        node=node,
        state_from=state_from,
        state_to=state_to,
        facts=facts,
        mode=mode,
        recorded_at=datetime.now(UTC),
    )
    trail.record(event)  # raises on failure -> fail closed
    return event


class DynamoDbAuditTrail:
    """Append-only audit trail backed by DynamoDB (MODE=aws).

    Items: pk=correlation_id, sk=AUDIT#{event_id}. Writes are guarded by
    attribute_not_exists(sk); persistence failure propagates (fail closed).
    """

    def __init__(self, table) -> None:
        self._table = table

    def record(self, event: AuditEvent) -> None:
        try:
            self._table.put_item(
                Item={
                    "pk": event.correlation_id,
                    "sk": f"AUDIT#{event.event_id}",
                    "node": event.node,
                    "state_from": event.state_from.value,
                    "state_to": event.state_to.value,
                    "facts_json": json.dumps(event.facts, separators=(",", ":")),
                    "mode": event.mode,
                    "recorded_at": event.recorded_at.isoformat(),
                },
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"duplicate audit event id: {event.event_id}") from exc
            raise  # fail closed: consequential actions never proceed un-audited

    def events_for(self, correlation_id: str) -> list[AuditEvent]:
        # String expression + explicit values: accepted by both the real
        # Table and the FakeTable double (Key objects would collide with
        # ExpressionAttributeValues on the real service).
        response = self._table.query(
            KeyConditionExpression="pk = :c AND begins_with(sk, :p)",
            ExpressionAttributeValues={":c": correlation_id, ":p": "AUDIT#"},
            ConsistentRead=True,
            ScanIndexForward=True,
        )
        return [self._to_event(item) for item in response["Items"]]

    def all_events(self) -> list[AuditEvent]:
        response = self._table.scan()
        return [self._to_event(item) for item in response["Items"]]

    @staticmethod
    def _to_event(item: dict) -> AuditEvent:
        return AuditEvent(
            event_id=item["sk"].removeprefix("AUDIT#"),
            correlation_id=item["pk"],
            node=item["node"],
            state_from=IncidentState(item["state_from"]),
            state_to=IncidentState(item["state_to"]),
            facts=json.loads(item["facts_json"]),
            mode=item["mode"],
            recorded_at=datetime.fromisoformat(item["recorded_at"]),
        )
