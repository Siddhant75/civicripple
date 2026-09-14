from civicripple.domain.enums import DecisionClassification, IncidentState
from civicripple.orchestration.replay import run_replay_scenario


def test_runner_executes_feasible_scenario() -> None:
    run = run_replay_scenario("feasible_reroute", correlation_id="incident-runner-1")
    assert run.ctx.state is IncidentState.RESOLVED
    assert run.ctx.decision.classification is DecisionClassification.AUTO_RESOLVABLE
    assert run.store.get("incident-runner-1") is not None
    assert len(run.trail.events_for("incident-runner-1")) >= 8


def test_runner_shares_injected_store() -> None:
    from civicripple.services.storage import InMemoryIncidentStore

    store = InMemoryIncidentStore()
    run_replay_scenario("no_impact", store=store, correlation_id="incident-runner-2")
    assert store.get("incident-runner-2").state is IncidentState.RESOLVED
