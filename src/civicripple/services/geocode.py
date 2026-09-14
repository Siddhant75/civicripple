"""Bounded demo geocoder.

Maps route designators in a notice to APPROXIMATE real-world corridor
geometries (curated index of Washington roads, labeled demo data). The
LLM never invents geometry: either a corridor matches deterministically
or the notice escalates. Coordinates are realistic approximations of the
named corridors, suitable for the demo map only."""

import re

from civicripple.domain.models import GeoShape

# route regex -> approximate corridor points ([lon, lat], real places)
_CORRIDORS: list[tuple[re.Pattern, list[list[float]]]] = [
    (re.compile(r"\bI-?5\b", re.I), [[-122.33, 47.6], [-122.325, 47.55], [-122.31, 47.48]]),
    (re.compile(r"\bI-?405\b", re.I), [[-122.32, 47.7], [-122.25, 47.62], [-122.2, 47.5]]),
    (re.compile(r"\bSR\s*-?167\b", re.I), [[-122.24, 47.44], [-122.22, 47.36], [-122.2, 47.3]]),
    (re.compile(r"\bI-?90\b", re.I), [[-122.36, 47.6], [-122.2, 47.58], [-122.03, 47.48]]),
    (re.compile(r"\bSR\s*-?520\b", re.I), [[-122.4, 47.65], [-122.3, 47.64], [-122.2, 47.63]]),
    (re.compile(r"\bUS\s*-?101\b", re.I), [[-123.94, 47.83], [-123.9, 47.78], [-123.86, 47.74]]),
    (re.compile(r"\bSR\s*-?20\b", re.I), [[-122.66, 48.3], [-122.62, 48.28], [-122.58, 48.26]]),
    (re.compile(r"\bSR\s*-?410\b", re.I), [[-122.0, 47.21], [-121.95, 47.18], [-121.9, 47.15]]),
    (re.compile(r"\bSR\s*-?14\b", re.I), [[-120.92, 45.72], [-120.88, 45.71], [-120.84, 45.7]]),
    (re.compile(r"\bferries\b|\bferry\b", re.I), [[-122.41, 47.6], [-122.44, 47.56]]),
]


def geocode_notice(text: str) -> GeoShape | None:
    if not text:
        return None
    for pattern, corridor in _CORRIDORS:
        if pattern.search(text):
            return GeoShape(kind="LineString", coordinates=corridor)
    return None


GEOCODED_FACT = "geometry_source: geocoded_corridor"
