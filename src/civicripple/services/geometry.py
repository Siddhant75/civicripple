"""Deterministic temporal and spatial impact engine.

Pure calculation: no LLM, no network, no AWS. Shapely conversion happens
only inside this module.
"""

from datetime import UTC, datetime

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from civicripple.domain.errors import UnsupportedGeometryError
from civicripple.domain.models import (
    DisruptionEvent,
    GeoShape,
    ImpactAssessment,
    OperationPlan,
    RouteCandidate,
)

_OPEN_ENDED = datetime.max.replace(tzinfo=UTC)


def _to_shapely(shape: GeoShape) -> BaseGeometry:
    """Convert a GeoShape to a Shapely geometry.

    Polygon coordinates follow the GeoJSON convention: a list of linear
    rings; only the exterior ring is used.
    """
    if shape.kind == "Point":
        return Point(shape.coordinates)
    if shape.kind == "LineString":
        return LineString(shape.coordinates)
    if shape.kind == "Polygon":
        return Polygon(shape.coordinates[0])
    raise UnsupportedGeometryError(f"unsupported geometry kind: {shape.kind!r}")


def intervals_overlap(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime
) -> bool:
    """Half-open interval overlap: boundary-touching is not overlap."""
    return start_a < end_b and start_b < end_a


def shapes_intersect(a: GeoShape, b: GeoShape) -> bool:
    return _to_shapely(a).intersects(_to_shapely(b))


def assess_impact(event: DisruptionEvent, plan: OperationPlan) -> ImpactAssessment:
    """Determine which planned route legs are affected by a disruption.

    A leg is affected only when BOTH temporal and spatial overlap are true.
    Results preserve route/leg order and de-duplicate stop IDs.
    """
    valid_from = event.valid_from
    valid_until = event.valid_until or _OPEN_ENDED
    disruption_geom = _to_shapely(event.geometry)

    affected_route_ids: list[str] = []
    affected_leg_ids: list[str] = []
    affected_stop_ids: list[str] = []
    reasons: list[str] = []
    any_temporal = False
    any_spatial = False

    for route in plan.routes:
        route_affected = False
        for leg in route.legs:
            temporal = intervals_overlap(
                leg.planned_departure, leg.planned_arrival, valid_from, valid_until
            )
            spatial = _to_shapely(leg.geometry).intersects(disruption_geom)
            any_temporal = any_temporal or temporal
            any_spatial = any_spatial or spatial
            if not (temporal and spatial):
                continue
            route_affected = True
            affected_leg_ids.append(leg.leg_id)
            reasons.append(f"temporal_overlap:{leg.leg_id}")
            reasons.append(f"spatial_overlap:{leg.leg_id}")
            for stop_id in (leg.from_stop_id, leg.to_stop_id):
                if stop_id not in affected_stop_ids:
                    affected_stop_ids.append(stop_id)
        if route_affected:
            affected_route_ids.append(route.route_id)

    return ImpactAssessment(
        disruption_id=event.event_id,
        operation_id=plan.operation_id,
        affected_route_ids=affected_route_ids,
        affected_leg_ids=affected_leg_ids,
        affected_stop_ids=affected_stop_ids,
        temporal_overlap=any_temporal,
        spatial_overlap=any_spatial,
        reasons=reasons,
    )


def validate_route_candidate(
    candidate: RouteCandidate, disruption: DisruptionEvent
) -> RouteCandidate:
    """Fail-closed independent validation of a route candidate.

    The candidate is clear of the disruption only when BOTH independent
    safety signals pass:

    1. no provider notice reports the exact replay sentinel
       ``avoidance_not_honored``;
    2. local geometry validation proves the candidate geometry does not
       intersect the disruption geometry.

    Returns a copied model; the original instance is never mutated.
    """
    provider_clean = not any(
        "avoidance_not_honored" in notice.lower()
        for notice in candidate.provider_notices
    )
    geometry_clear = not shapes_intersect(candidate.geometry, disruption.geometry)

    return candidate.model_copy(
        update={"independently_clear_of_disruption": provider_clean and geometry_clear}
    )
