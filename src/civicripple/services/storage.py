"""Incident persistence. In-memory for local replay; Phase 3 adds DynamoDB
behind the same interface."""

from civicripple.domain.models import IncidentRecord


class InMemoryIncidentStore:
    def __init__(self) -> None:
        self._records: dict[str, IncidentRecord] = {}

    def save(self, record: IncidentRecord) -> None:
        self._records[record.correlation_id] = record

    def get(self, correlation_id: str) -> IncidentRecord | None:
        return self._records.get(correlation_id)

    def list(self) -> list[IncidentRecord]:
        return list(self._records.values())


class DynamoDbIncidentStore:
    """Incident persistence on DynamoDB (MODE=aws). sk=INCIDENT is the
    current-state row, overwritten per transition."""

    def __init__(self, table) -> None:
        self._table = table

    def save(self, record: IncidentRecord) -> None:
        self._table.put_item(
            Item={
                "pk": record.correlation_id,
                "sk": "INCIDENT",
                "record_json": record.model_dump_json(),
            }
        )

    def get(self, correlation_id: str) -> IncidentRecord | None:
        response = self._table.get_item(
            Key={"pk": correlation_id, "sk": "INCIDENT"}, ConsistentRead=True
        )
        item = response.get("Item")
        if item is None:
            return None
        return IncidentRecord.model_validate_json(item["record_json"])

    def list(self) -> list[IncidentRecord]:
        response = self._table.scan()
        return [
            IncidentRecord.model_validate_json(item["record_json"])
            for item in response["Items"]
            if item["sk"] == "INCIDENT"
        ]
