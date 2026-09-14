from pathlib import Path

from civicripple.domain.enums import IncidentState
from civicripple.orchestration.replay import run_replay_scenario

FIXTURES = Path("src/civicripple/fixtures")


def test_replay_run_persists_map_snapshot() -> None:
    run = run_replay_scenario("feasible_reroute", correlation_id="incident-map-1")
    record = run.store.get("incident-map-1")
    snap = record.map
    assert snap is not None
    assert snap.depot.lon == -122.4
    assert {s.stop_id for s in snap.stops} == {
        "stop-a1", "stop-a2", "stop-a3", "stop-a4",
        "stop-b1", "stop-b2", "stop-b3", "stop-b4",
    }
    affected = [leg for leg in snap.legs if leg.affected]
    assert [leg.leg_id for leg in affected] == ["leg-b2"]
    assert snap.disruption_geometry is not None
    assert snap.candidate_geometry is not None
    assert snap.candidate_duration_s == 3120
    b2 = next(s for s in snap.stops if s.stop_id == "stop-b2")
    assert b2.planned_arrival is not None


def test_no_impact_run_has_candidate_geometry_none() -> None:
    run = run_replay_scenario("no_impact", correlation_id="incident-map-2")
    snap = run.store.get("incident-map-2").map
    assert snap is not None
    assert all(not leg.affected for leg in snap.legs)
    assert snap.candidate_geometry is None
    assert snap.disruption_geometry is not None


def test_all_runs_complete_with_snapshots() -> None:
    for scenario in ("feasible_reroute", "infeasible_reroute", "avoidance_failure"):
        run = run_replay_scenario(scenario, correlation_id=f"incident-map-{scenario}")
        record = run.store.get(f"incident-map-{scenario}")
        assert record.state in (IncidentState.RESOLVED, IncidentState.REVIEW_REQUIRED)
        assert record.map is not None
