from civicripple.orchestration import replay as replay_mod


class FakeBedrockModel:
    calls = []

    def __init__(self, **kwargs):
        type(self).calls.append(kwargs)
        self.kwargs = kwargs

    @classmethod
    def reset(cls):
        cls.calls = []


def test_build_live_agents_wires_bedrock(monkeypatch) -> None:
    FakeBedrockModel.reset()
    import civicripple.orchestration.runtime as runtime_mod

    captured = {"models": [], "builders": 0}

    def fake_build_bedrock_model(settings):
        return FakeBedrockModel(
            model_id=settings.bedrock_model_id, region_name=settings.aws_region
        )

    def fake_builder(model):
        captured["builders"] += 1
        captured["models"].append(model)
        return object()  # sentinel agent; graph never runs in this test

    monkeypatch.setattr(runtime_mod, "build_bedrock_model", fake_build_bedrock_model)
    monkeypatch.setattr(replay_mod, "aws_settings", lambda: ("us-east-1", "test-model-id"))
    monkeypatch.setattr(
        "civicripple.agents.disruption_extractor.build_extractor_agent", fake_builder
    )
    monkeypatch.setattr(
        "civicripple.agents.evidence_verifier.build_verifier_agent", fake_builder
    )
    monkeypatch.setattr(
        "civicripple.agents.options_agent.build_options_agent", fake_builder
    )

    replay_mod._build_live_agents()
    assert captured["builders"] == 3
    assert all(m.kwargs["model_id"] == "test-model-id" for m in captured["models"])


def test_live_flag_routes_through_live_builder(monkeypatch) -> None:
    scripted = replay_mod.run_replay_scenario(
        "feasible_reroute", correlation_id="incident-live-0a"
    )
    calls = []

    def fake_live_builder():
        calls.append(True)
        # reuse scripted agents: same graph behavior, zero real calls
        return _scripted_agents("feasible_reroute")

    def fake_live_infra():
        # scripted infra: no real AWS calls in this test
        return (
            replay_mod.ReplayRoutingProvider(candidate_name="feasible.json"),
            replay_mod.AuditTrail(),
            replay_mod.InMemoryIncidentStore(),
        )

    monkeypatch.setattr(replay_mod, "_build_live_agents", fake_live_builder)
    monkeypatch.setattr(replay_mod, "_build_live_infra", fake_live_infra)
    run = replay_mod.run_replay_scenario(
        "feasible_reroute", correlation_id="incident-live-1", live=True
    )
    assert calls == [True]
    assert run.ctx.state == scripted.ctx.state


def _scripted_agents(scenario: str):
    from pathlib import Path

    from civicripple.agents.disruption_extractor import build_extractor_agent
    from civicripple.agents.evidence_verifier import build_verifier_agent
    from civicripple.agents.options_agent import build_options_agent
    from civicripple.domain.models import (
        DisruptionEventCandidate,
        OptionsReport,
        VerificationVerdict,
    )
    from civicripple.services.replay_model import ReplayModel

    replays = Path("src/civicripple/fixtures") / "model_replays" / scenario
    extractor = build_extractor_agent(
        ReplayModel(
            [DisruptionEventCandidate.model_validate_json((replays / "extractor.json").read_text())]
        )
    )
    verifier = build_verifier_agent(
        ReplayModel([VerificationVerdict.model_validate_json((replays / "verifier.json").read_text())])
    )
    if (replays / "options.json").exists():
        options = build_options_agent(
            ReplayModel([OptionsReport.model_validate_json((replays / "options.json").read_text())])
        )
    else:
        options = build_options_agent(ReplayModel([]))
    return extractor, verifier, options


def test_replay_mode_stays_scripted() -> None:
    run = replay_mod.run_replay_scenario(
        "feasible_reroute", correlation_id="incident-live-2", live=False
    )
    assert run.ctx.state.value == "RESOLVED"  # scripted path unchanged


def test_endpoint_rejects_live_without_credentials(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from civicripple.app import create_app

    def boom(*args, **kwargs):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(replay_mod, "_build_live_agents", boom)
    client = TestClient(create_app())
    response = client.post(
        "/incidents/incident-live-3/replay",
        json={"scenario": "feasible_reroute", "live": True},
    )
    assert response.status_code == 502
    assert "no credentials" in response.json()["detail"]
