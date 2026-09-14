"""Routing provider adapter boundary.

Both implementations share one interface: `request_candidate(plan, route,
disruption) -> RouteCandidate`. Replay returns a recorded deterministic
response; Phase 3's Amazon Location adapter (services/amazon_location.py)
calls the real Routes V2 API. Provider avoidance is NEVER trusted directly —
services.geometry.validate_route_candidate independently re-checks."""

from pathlib import Path

from civicripple.domain.models import (
    DisruptionEvent,
    OperationPlan,
    RouteCandidate,
    RoutePlan,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class ReplayRoutingProvider:
    def __init__(self, candidate_name: str = "") -> None:
        self._candidate_path = FIXTURES / "route_candidates" / candidate_name

    def request_candidate(
        self, plan: OperationPlan, route: RoutePlan, disruption: DisruptionEvent
    ) -> RouteCandidate:
        candidate = RouteCandidate.model_validate_json(self._candidate_path.read_text())
        if candidate.route_id != route.route_id:
            raise RuntimeError(
                f"replay routing fixture {self._candidate_path.name} serves "
                f"route {candidate.route_id}, not {route.route_id}"
            )
        return candidate
