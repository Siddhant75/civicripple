import json

import pytest

from civicripple.domain.models import IncidentRecord
from civicripple.services.agentcore_proxy import invoke_cloud_scenario


class FakeAgentCoreClient:
    def __init__(self, record: dict) -> None:
        self.record = record
        self.captured: dict | None = None

    def invoke_agent_runtime(self, **kwargs):
        self.captured = kwargs
        return {"response": iter([json.dumps(self.record).encode()])}


def test_invoke_cloud_returns_record(monkeypatch) -> None:
    record = IncidentRecord(
        correlation_id="incident-cloud-1",
        state="RESOLVED",
        created_at="2026-09-10T00:00:00Z",
        updated_at="2026-09-10T00:00:00Z",
    )
    client = FakeAgentCoreClient(record.model_dump(mode="json"))
    monkeypatch.setenv(
        "AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x"
    )
    monkeypatch.setattr("civicripple.services.agentcore_proxy._client", lambda: client)
    got = invoke_cloud_scenario("feasible_reroute", "incident-cloud-1")
    assert got.correlation_id == "incident-cloud-1"
    assert got.state == "RESOLVED"
    payload = json.loads(client.captured["payload"])
    assert payload["scenario"] == "feasible_reroute"
    assert payload["correlation_id"] == "incident-cloud-1"
    assert len(client.captured["runtimeSessionId"]) >= 33


def test_invoke_cloud_fails_loud_without_arn(monkeypatch) -> None:
    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN", raising=False)
    monkeypatch.setattr(
        "civicripple.services.agentcore_proxy._runtime_file_arn", lambda: None
    )
    with pytest.raises(RuntimeError, match="AGENTCORE_RUNTIME_ARN"):
        invoke_cloud_scenario("feasible_reroute", "incident-cloud-2")


def test_remote_replay_endpoint(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from civicripple.app import create_app

    record = IncidentRecord(
        correlation_id="incident-remote-1",
        state="RESOLVED",
        created_at="2026-09-10T00:00:00Z",
        updated_at="2026-09-10T00:00:00Z",
    )
    client_fake = FakeAgentCoreClient(record.model_dump(mode="json"))
    monkeypatch.setenv(
        "AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x"
    )
    monkeypatch.setattr(
        "civicripple.services.agentcore_proxy._client", lambda: client_fake
    )
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/incidents/incident-remote-1/replay",
        json={"scenario": "feasible_reroute", "remote": True},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "RESOLVED"
    # persisted into the app's own store for the dashboard listing
    listing = client.get("/incidents").json()["incidents"]
    assert any(i["correlation_id"] == "incident-remote-1" for i in listing)


def test_remote_replay_fail_loud(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from civicripple.app import create_app
    from civicripple.services import agentcore_proxy

    def boom(*a, **k):
        raise RuntimeError("runtime not deployed")

    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN", raising=False)
    monkeypatch.setattr(agentcore_proxy, "_runtime_file_arn", lambda: None)
    client = TestClient(create_app())
    response = client.post(
        "/incidents/incident-remote-2/replay",
        json={"scenario": "feasible_reroute", "remote": True},
    )
    assert response.status_code == 502
    assert "cloud run failed" in response.json()["detail"]
