"""Amazon Location Service Routes V2 adapter (geo-routes client).

Real provider responses are normalized to the provider-neutral
RouteCandidate. Avoidance is best-effort: violations surface as response
Notices, translated here to the sentinel 'avoidance_not_honored' so
services.geometry.validate_route_candidate stays the single fail-closed
gate (provider signal AND independent geometry check). AWS response shapes
never leak past this boundary."""

import boto3
from botocore.exceptions import ClientError  # noqa: F401 - re-exported surface for callers

from civicripple.domain.models import (
    DisruptionEvent,
    GeoShape,
    OperationPlan,
    RouteCandidate,
    RoutePlan,
)

AVOID_VIOLATION_SENTINEL = "avoidance_not_honored"


def build_geo_routes_client(region_name: str):
    return boto3.client("geo-routes", region_name=region_name)


def _route_positions(
    plan: OperationPlan, route: RoutePlan
) -> tuple[list[float], list[float], list[list[float]]]:
    """Origin (depot), destination (last stop), pass-through waypoints."""
    stops = [stop.location for stop in route.stops]
    origin = [plan.depot.lon, plan.depot.lat]
    destination = [stops[-1].lon, stops[-1].lat]
    waypoints = [[loc.lon, loc.lat] for loc in stops[:-1]]
    return origin, destination, waypoints


def _avoid_area(disruption: DisruptionEvent) -> dict:
    if disruption.geometry.kind != "Polygon":
        raise RuntimeError(
            "avoidance area requires Polygon disruption geometry; "
            f"got {disruption.geometry.kind} — never guess an area"
        )
    ring = disruption.geometry.coordinates[0]
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise RuntimeError("avoidance polygon ring must be closed with >= 4 positions")
    return {"Areas": [{"Geometry": {"Polygon": [ring]}}]}


def _leg_details(leg: dict) -> dict:
    """Return the leg's mode-specific *LegDetails block (Vehicle, Ferry,
    Transit, ...). Real responses mix leg types on one route."""
    for key, value in leg.items():
        if key.endswith("LegDetails") and isinstance(value, dict):
            return value
    return {}


def _normalize_notices(response: dict) -> list[str]:
    """Merge top-level and per-leg notices; translate avoid violations."""
    raw: list[dict] = list(response.get("Notices", []))
    for leg in response.get("Routes", [{}])[0].get("Legs", []):
        raw.extend(_leg_details(leg).get("Notices", []))
    notices: list[str] = []
    for notice in raw:
        code = str(notice.get("Code", ""))
        if "violatedavoid" in code.lower():
            notices.append(AVOID_VIOLATION_SENTINEL)
        elif code:
            notices.append(code.lower())
    return notices


def _route_totals(response: dict) -> tuple[int, int]:
    """Total distance (m) and duration (s) summed across legs.

    Real V2 responses carry per-leg totals inside
    Legs[i].<Mode>LegDetails.Summary.Overview; there is no top-level
    route Summary, and legs may mix Vehicle/Ferry/etc. types."""
    legs = response["Routes"][0]["Legs"]
    distance = sum(
        int(_leg_details(leg)["Summary"]["Overview"]["Distance"]) for leg in legs
    )
    duration = sum(
        int(_leg_details(leg)["Summary"]["Overview"]["Duration"]) for leg in legs
    )
    return distance, duration


def _concatenated_geometry(response: dict) -> GeoShape:
    line: list[list[float]] = []
    for leg in response["Routes"][0]["Legs"]:
        for position in leg.get("Geometry", {}).get("LineString", []):
            if not line or line[-1] != position:
                line.append(position)
    if len(line) < 2:
        # No geometry means avoidance can never be proven: fail closed.
        raise RuntimeError("route response carried no leg geometry; cannot validate avoidance")
    return GeoShape(kind="LineString", coordinates=line)


class AmazonLocationRoutingProvider:
    def __init__(self, client) -> None:
        self._client = client

    def request_candidate(
        self, plan: OperationPlan, route: RoutePlan, disruption: DisruptionEvent
    ) -> RouteCandidate:
        origin, destination, waypoints = _route_positions(plan, route)
        request = {
            "Origin": origin,
            "Destination": destination,
            "TravelMode": "Car",
            "Avoid": _avoid_area(disruption),
            "DepartureTime": route.legs[0].planned_departure.isoformat(),
            "LegGeometryFormat": "Simple",  # geometry is required for the
            # independent avoidance check; without it we fail closed.
            "Waypoints": [
                {"Position": position, "PassThrough": True} for position in waypoints
            ],
        }
        response = self._client.calculate_routes(**request)  # ClientError propagates
        distance_m, duration_s = _route_totals(response)
        return RouteCandidate(
            route_id=route.route_id,
            provider="amazon-location",
            geometry=_concatenated_geometry(response),
            distance_m=distance_m,
            duration_s=duration_s,
            provider_notices=_normalize_notices(response),
            independently_clear_of_disruption=False,
        )
