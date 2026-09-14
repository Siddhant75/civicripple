from pathlib import Path

import pytest
from pydantic import ValidationError

from civicripple.domain.models import OperationPlan, WhatIfContext, WhatIfVariant


@pytest.fixture
def plan_fixture() -> OperationPlan:
    return OperationPlan.model_validate_json(
        Path("src/civicripple/fixtures/operation_plan.json").read_text()
    )


def _variant(**kwargs) -> dict:
    return {"action": "delay_departure", "seconds": 600, **kwargs}


def test_variant_delay_ok() -> None:
    v = WhatIfVariant.model_validate(_variant())
    assert v.action == "delay_departure" and v.seconds == 600


def test_variant_delay_bounds() -> None:
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate(_variant(seconds=30))  # below 60
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate(_variant(seconds=7200))  # above 3600


def test_variant_requires_action_fields() -> None:
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate({"action": "drop_stop"})  # stop_id missing
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate(
            {"action": "shift_window", "stop_id": "s1"}
        )  # new_end missing
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate({"action": "delay_departure"})  # seconds missing


def test_variant_unknown_action_rejected() -> None:
    with pytest.raises(ValidationError):
        WhatIfVariant.model_validate({"action": "teleport"})


def test_whatif_context_roundtrip(plan_fixture: OperationPlan) -> None:
    ctx = WhatIfContext(plan=plan_fixture, route_id="route-b", candidate=None)
    assert ctx.route_id == "route-b"


from civicripple.domain.enums import DecisionClassification
from civicripple.domain.models import DisruptionEvent, RouteCandidate
from civicripple.services.geometry import validate_route_candidate
from civicripple.services.whatif import apply_variant, evaluate_variant


def _candidate() -> RouteCandidate:
    # Mirror the pipeline: whatif_context stores the VALIDATED candidate.
    raw = RouteCandidate.model_validate_json(
        (Path("src/civicripple/fixtures/route_candidates/infeasible.json").read_text())
    )
    disruption = DisruptionEvent.model_validate_json(
        (Path("src/civicripple/fixtures/notices/infeasible_closure.json").read_text())
    )
    return validate_route_candidate(raw, disruption)


def test_drop_stop_removes_stop_and_incoming_leg(plan_fixture) -> None:
    plan = apply_variant(
        plan_fixture,
        "route-b",
        WhatIfVariant.model_validate({"action": "drop_stop", "stop_id": "stop-b2"}),
    )
    route = next(r for r in plan.routes if r.route_id == "route-b")
    assert "stop-b2" not in {s.stop_id for s in route.stops}
    assert "leg-b2" not in {l.leg_id for l in route.legs}
    assert len(route.stops) == 3 and len(route.legs) == 3


def test_drop_unknown_stop_raises(plan_fixture) -> None:
    with pytest.raises(KeyError):
        apply_variant(
            plan_fixture,
            "route-b",
            WhatIfVariant.model_validate({"action": "drop_stop", "stop_id": "nope"}),
        )


def test_delay_shifts_all_leg_times(plan_fixture) -> None:
    plan = apply_variant(
        plan_fixture,
        "route-b",
        WhatIfVariant.model_validate({"action": "delay_departure", "seconds": 600}),
    )
    route = next(r for r in plan.routes if r.route_id == "route-b")
    assert route.legs[0].planned_departure.isoformat() == "2026-09-03T09:10:00+00:00"
    assert route.legs[0].planned_arrival.isoformat() == "2026-09-03T09:25:00+00:00"


def test_shift_window_moves_only_that_stop(plan_fixture) -> None:
    plan = apply_variant(
        plan_fixture,
        "route-b",
        WhatIfVariant.model_validate(
            {"action": "shift_window", "stop_id": "stop-b2", "new_end": "2026-09-03T10:15:00Z"}
        ),
    )
    route = next(r for r in plan.routes if r.route_id == "route-b")
    b2 = next(s for s in route.stops if s.stop_id == "stop-b2")
    assert b2.time_window.end.isoformat() == "2026-09-03T10:15:00+00:00"
    b1 = next(s for s in route.stops if s.stop_id == "stop-b1")
    assert b1.time_window.end.isoformat() == "2026-09-03T11:00:00+00:00"  # untouched


def test_evaluate_variant_drop_stop_makes_route_feasible(plan_fixture) -> None:
    result = evaluate_variant(
        plan_fixture,
        "route-b",
        _candidate(),
        WhatIfVariant.model_validate({"action": "drop_stop", "stop_id": "stop-b2"}),
    )
    assert result.decision.classification is DecisionClassification.AUTO_RESOLVABLE
    assert result.feasibility.feasible is True
    assert "stop-b2" not in {a.stop_id for a in result.feasibility.stop_arrivals}
    assert result.explanation  # composed from computed facts


def test_evaluate_variant_small_delay_still_infeasible(plan_fixture) -> None:
    result = evaluate_variant(
        plan_fixture,
        "route-b",
        _candidate(),
        WhatIfVariant.model_validate({"action": "delay_departure", "seconds": 300}),
    )
    assert result.decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
    assert result.feasibility.feasible is False
