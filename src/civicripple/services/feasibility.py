"""Deterministic arrival propagation and hard time-window feasibility.

Pure calculation: no LLM, no network, no AWS. Fixed stop order is
preserved — no optimization, reassignment, or reordering.
"""

from datetime import timedelta

from civicripple.domain.models import (
    ConstraintViolation,
    FeasibilityResult,
    RouteCandidate,
    RoutePlan,
    StopArrival,
)


def _distributed_leg_durations(route: RoutePlan, candidate_duration_s: int) -> list[int]:
    """Spread the candidate's added duration across legs proportionally.

    The integer remainder is assigned to the final leg so the sum of
    distributed leg durations equals ``candidate_duration_s`` exactly.
    """
    original_total = sum(leg.duration_s for leg in route.legs)
    added = candidate_duration_s - original_total
    if added <= 0 or original_total == 0:
        return [leg.duration_s for leg in route.legs]

    distributed = [
        leg.duration_s + (added * leg.duration_s) // original_total
        for leg in route.legs
    ]
    remainder = candidate_duration_s - sum(distributed)
    distributed[-1] += remainder
    return distributed


def propagate_arrivals(route: RoutePlan, candidate_duration_s: int) -> list[StopArrival]:
    """Recompute stop arrival times under a candidate route duration.

    Each stop's service duration is carried into the next departure.
    """
    leg_durations = _distributed_leg_durations(route, candidate_duration_s)
    stops_by_id = {stop.stop_id: stop for stop in route.stops}

    arrivals: list[StopArrival] = []
    departure = route.legs[0].planned_departure
    for leg, duration_s in zip(route.legs, leg_durations):
        arrival = departure + timedelta(seconds=duration_s)
        arrivals.append(StopArrival(stop_id=leg.to_stop_id, arrival_at=arrival))
        service_s = stops_by_id[leg.to_stop_id].service_duration_s
        departure = arrival + timedelta(seconds=service_s)
    return arrivals


def evaluate_feasibility(route: RoutePlan, candidate: RouteCandidate) -> FeasibilityResult:
    """Evaluate every hard delivery time window under a candidate route.

    A stop violates its window only when ``arrival_at > time_window.end``;
    arrival exactly at the end is allowed.
    """
    original_total = sum(leg.duration_s for leg in route.legs)
    added_duration_s = candidate.duration_s - original_total

    arrivals = propagate_arrivals(route, candidate.duration_s)
    stops_by_id = {stop.stop_id: stop for stop in route.stops}

    violations: list[ConstraintViolation] = []
    for arrival in arrivals:
        stop = stops_by_id[arrival.stop_id]
        if arrival.arrival_at > stop.time_window.end:
            lateness_s = int(
                (arrival.arrival_at - stop.time_window.end).total_seconds()
            )
            violations.append(
                ConstraintViolation(
                    stop_id=stop.stop_id,
                    code="TIME_WINDOW_LATE",
                    message=(
                        f"arrival {arrival.arrival_at.isoformat()} exceeds "
                        f"window end {stop.time_window.end.isoformat()}"
                    ),
                    lateness_s=lateness_s,
                )
            )

    return FeasibilityResult(
        feasible=not violations,
        stop_arrivals=arrivals,
        violations=violations,
        added_duration_s=added_duration_s,
    )
