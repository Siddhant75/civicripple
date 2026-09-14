"""Deterministic what-if variant engine.

The coordinator's hypotheticals are re-run through the SAME frozen
feasibility/policy engines the agent used — no new logic, no LLM.
Explanations cite computed facts only (violations, arrival deltas,
classification reason codes)."""

from datetime import datetime, timedelta

from civicripple.domain.models import (
    ImpactAssessment,
    OperationPlan,
    RouteCandidate,
    WhatIfResult,
    WhatIfVariant,
)
from civicripple.domain.policies import classify_incident
from civicripple.services.feasibility import evaluate_feasibility


def _shift(iso: str, delta: timedelta) -> str:
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) + delta).isoformat()


def apply_variant(
    plan: OperationPlan, route_id: str, variant: WhatIfVariant
) -> OperationPlan:
    """Return a modified plan copy. Rules (spec-fixed): drop_stop removes the
    stop AND its incoming leg (never merges legs); delay_departure shifts
    every leg departure/arrival on the route uniformly; shift_window moves
    only the named stop's window end."""
    data = plan.model_dump(mode="json")
    for route in data["routes"]:
        if route["route_id"] != route_id:
            continue
        if variant.action == "drop_stop":
            if not any(s["stop_id"] == variant.stop_id for s in route["stops"]):
                raise KeyError(variant.stop_id)
            route["stops"] = [
                s for s in route["stops"] if s["stop_id"] != variant.stop_id
            ]
            route["legs"] = [
                l for l in route["legs"] if l["to_stop_id"] != variant.stop_id
            ]
        elif variant.action == "delay_departure":
            delta = timedelta(seconds=variant.seconds)
            for leg in route["legs"]:
                leg["planned_departure"] = _shift(leg["planned_departure"], delta)
                leg["planned_arrival"] = _shift(leg["planned_arrival"], delta)
        elif variant.action == "shift_window":
            hits = [s for s in route["stops"] if s["stop_id"] == variant.stop_id]
            if not hits:
                raise KeyError(variant.stop_id)
            hits[0]["time_window"]["end"] = variant.new_end.isoformat()
    return OperationPlan.model_validate(data)


def _whatif_impact(base_plan: OperationPlan, route_id: str) -> ImpactAssessment:
    """Impact-shaped input for the policy gate: the variant only changes one
    route's timings, so the affected set is that route's whole remainder."""
    route = next(r for r in base_plan.routes if r.route_id == route_id)
    return ImpactAssessment(
        disruption_id="whatif",
        operation_id=base_plan.operation_id,
        affected_route_ids=[route_id],
        affected_leg_ids=[l.leg_id for l in route.legs],
        affected_stop_ids=[s.stop_id for s in route.stops],
        temporal_overlap=True,
        spatial_overlap=True,
        reasons=[f"whatif:{route_id}"],
    )


def evaluate_variant(
    plan: OperationPlan,
    route_id: str,
    candidate: RouteCandidate,
    variant: WhatIfVariant,
) -> WhatIfResult:
    route = next(r for r in plan.routes if r.route_id == route_id)
    baseline = evaluate_feasibility(route, candidate)

    modified = apply_variant(plan, route_id, variant)
    modified_route = next(r for r in modified.routes if r.route_id == route_id)
    feasibility = evaluate_feasibility(modified_route, candidate)
    decision = classify_incident(
        _whatif_impact(modified, route_id), candidate, feasibility
    )

    baseline_arrivals = {a.stop_id: a.arrival_at for a in baseline.stop_arrivals}
    facts: list[str] = []
    for a in feasibility.stop_arrivals:
        before = baseline_arrivals.get(a.stop_id)
        if before is not None and a.arrival_at != before:
            delta_s = int((a.arrival_at - before).total_seconds())
            facts.append(
                f"{a.stop_id} arrival {'+' if delta_s >= 0 else ''}{delta_s}s vs baseline"
            )
    for v in feasibility.violations:
        facts.append(f"{v.stop_id}: {v.code} +{v.lateness_s}s past window end")
    if not feasibility.violations and baseline.violations:
        facts.append("all hard time windows now pass")
    explanation = (
        f"{variant.action.replace('_', ' ')} applied to {route_id}: "
        f"classification {decision.classification.value}. "
        + ("; ".join(facts) if facts else "arrival times unchanged.")
    )
    return WhatIfResult(
        variant=variant,
        feasibility=feasibility,
        decision=decision,
        explanation=explanation,
    )
