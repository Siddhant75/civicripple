import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from civicripple.domain.models import DisruptionEvent, OperationPlan
from civicripple.services.amazon_location import AmazonLocationRoutingProvider

FIXTURES = Path("src/civicripple/fixtures")


class FakeGeoRoutesClient:
    """Records the calculate_routes request; returns a recorded response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.captured_request: dict | None = None

    def calculate_routes(self, **request) -> dict:
        self.captured_request = request
        if "raise" in self.response:
            raise ClientError(
                {"Error": {"Code": self.response["raise"], "Message": "boom"}},
                "CalculateRoutes",
            )
        return self.response


def _plan() -> OperationPlan:
    return OperationPlan.model_validate_json(
        (FIXTURES / "operation_plan.json").read_text()
    )


def _disruption() -> DisruptionEvent:
    return DisruptionEvent.model_validate_json(
        (FIXTURES / "notices" / "feasible_closure.json").read_text()
    )


def _response(name: str) -> dict:
    return json.loads((FIXTURES / "aws_responses" / f"{name}.json").read_text())


def _route_b(plan: OperationPlan):
    return next(r for r in plan.routes if r.route_id == "route-b")


def test_adapter_builds_avoid_area_request() -> None:
    client = FakeGeoRoutesClient(_response("calculate_routes_feasible"))
    plan = _plan()
    provider = AmazonLocationRoutingProvider(client)
    provider.request_candidate(plan, _route_b(plan), _disruption())
    request = client.captured_request
    assert request["Origin"] == [-122.4, 47.6]  # depot [lon, lat]
    assert request["Destination"] == [-122.44, 47.56]  # last stop
    assert request["TravelMode"] == "Car"
    avoid_area = request["Avoid"]["Areas"][0]["Geometry"]["Polygon"][0]
    assert avoid_area[0] == avoid_area[-1]  # closed ring
    assert [-122.418, 47.583] in avoid_area
    assert all(len(w["Position"]) == 2 for w in request["Waypoints"])


def test_adapter_normalizes_clean_response_to_candidate() -> None:
    client = FakeGeoRoutesClient(_response("calculate_routes_feasible"))
    plan = _plan()
    provider = AmazonLocationRoutingProvider(client)
    candidate = provider.request_candidate(plan, _route_b(plan), _disruption())
    assert candidate.route_id == "route-b"
    assert candidate.provider == "amazon-location"
    assert candidate.distance_m == 5200
    assert candidate.duration_s == 3120
    assert candidate.geometry.kind == "LineString"
    assert candidate.provider_notices == []


def test_adapter_translates_avoid_violation_notice_to_sentinel() -> None:
    from civicripple.services.geometry import validate_route_candidate

    client = FakeGeoRoutesClient(_response("calculate_routes_violation"))
    plan = _plan()
    provider = AmazonLocationRoutingProvider(client)
    candidate = provider.request_candidate(plan, _route_b(plan), _disruption())
    assert "avoidance_not_honored" in candidate.provider_notices
    # the deterministic gate must be able to reject on this signal alone
    validated = validate_route_candidate(candidate, _disruption())
    assert validated.independently_clear_of_disruption is False


def test_adapter_rejects_non_polygon_disruption_geometry() -> None:
    from civicripple.domain.models import GeoShape

    client = FakeGeoRoutesClient(_response("calculate_routes_feasible"))
    plan = _plan()
    disruption = _disruption().model_copy(
        update={
            "geometry": GeoShape(
                kind="LineString",
                coordinates=[[-122.41, 47.59], [-122.42, 47.58]],
            )
        }
    )
    provider = AmazonLocationRoutingProvider(client)
    with pytest.raises(RuntimeError, match="Polygon"):
        provider.request_candidate(plan, _route_b(plan), disruption)


def test_adapter_propagates_client_error() -> None:
    client = FakeGeoRoutesClient({"raise": "ThrottlingException"})
    plan = _plan()
    provider = AmazonLocationRoutingProvider(client)
    with pytest.raises(ClientError):
        provider.request_candidate(plan, _route_b(plan), _disruption())
