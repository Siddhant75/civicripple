from fastapi.testclient import TestClient

from civicripple.app import create_app
from civicripple.config import Settings
from civicripple.services.storage import InMemoryIncidentStore


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mode_is_visible() -> None:
    client = TestClient(create_app(Settings(mode="local_replay")))
    body = client.get("/mode").json()
    assert body["mode"] == "local_replay"
    assert body["store"] == "in_memory"


def test_mode_shows_aws_when_configured() -> None:
    from civicripple.services.audit import DynamoDbAuditTrail
    from civicripple.services.storage import DynamoDbIncidentStore

    settings = Settings(mode="aws")
    client = TestClient(
        create_app(
            settings,
            store=DynamoDbIncidentStore(table=object()),
            trail=DynamoDbAuditTrail(table=object()),
        )
    )
    body = client.get("/mode").json()
    assert body["mode"] == "aws"
    assert body["store"] == "dynamodb"
    assert body["region"] == "us-east-1"


def _seed_incident(store, correlation_id: str, state=None):
    from datetime import datetime, timezone

    from civicripple.domain.enums import IncidentState
    from civicripple.domain.models import IncidentRecord

    store.save(
        IncidentRecord(
            correlation_id=correlation_id,
            state=state or IncidentState.REVIEW_REQUIRED,
            created_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 3, 9, tzinfo=timezone.utc),
        )
    )


def test_operations_endpoint_returns_fixture_plan() -> None:
    client = TestClient(create_app())
    response = client.get("/operations/op-demo-2026-09-03")
    assert response.status_code == 200
    assert response.json()["operation_id"] == "op-demo-2026-09-03"
    assert len(response.json()["routes"]) == 2


def test_operations_endpoint_404_on_unknown() -> None:
    client = TestClient(create_app())
    assert client.get("/operations/nope").status_code == 404


def test_incidents_list_newest_first() -> None:
    from datetime import datetime, timedelta, timezone

    from civicripple.domain.enums import IncidentState
    from civicripple.domain.models import IncidentRecord

    store = InMemoryIncidentStore()
    base = datetime(2026, 9, 3, 9, tzinfo=timezone.utc)
    for i, corr in enumerate(("old", "new")):
        store.save(
            IncidentRecord(
                correlation_id=corr,
                state=IncidentState.RESOLVED,
                created_at=base,
                updated_at=base + timedelta(minutes=i),
            )
        )
    client = TestClient(create_app(store=store))
    body = client.get("/incidents").json()
    assert [i["correlation_id"] for i in body["incidents"]] == ["new", "old"]


def test_incident_detail_404_on_unknown() -> None:
    client = TestClient(create_app())
    assert client.get("/incidents/missing").status_code == 404


def test_replay_endpoint_runs_scenario() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/incidents/incident-api-replay/replay", json={"scenario": "feasible_reroute"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "RESOLVED"
    listing = client.get("/incidents").json()["incidents"]
    assert any(i["correlation_id"] == "incident-api-replay" for i in listing)


def test_replay_endpoint_rejects_unknown_scenario() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/incidents/incident-x/replay", json={"scenario": "does_not_exist"}
    )
    assert response.status_code == 400


def _seed_review_incident(client: TestClient) -> str:
    # A replayed infeasible incident lands in REVIEW_REQUIRED with a payload.
    response = client.post(
        "/incidents/incident-review-demo/replay", json={"scenario": "infeasible_reroute"}
    )
    assert response.status_code == 200
    return "incident-review-demo"


def test_review_approve_resolves_incident() -> None:
    client = TestClient(create_app())
    correlation_id = _seed_review_incident(client)
    response = client.post(
        f"/incidents/{correlation_id}/review",
        json={"decision": "approve", "note": "late arrival acceptable"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "RESOLVED"
    events = client.get(f"/audit/{correlation_id}").json()["events"]
    review_events = [e for e in events if e["node"] == "review"]
    assert [e["state_to"] for e in review_events][-2:] == ["HUMAN_APPROVED", "RESOLVED"]
    assert any(e["facts"].get("note") == "late arrival acceptable" for e in review_events)


def test_review_reject_opens_incident() -> None:
    client = TestClient(create_app())
    correlation_id = _seed_review_incident(client)
    response = client.post(
        f"/incidents/{correlation_id}/review", json={"decision": "reject"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "OPEN"


def test_review_rejects_invalid_state() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-auto/replay", json={"scenario": "feasible_reroute"})
    response = client.post("/incidents/incident-auto/review", json={"decision": "approve"})
    assert response.status_code == 409


def test_review_404_on_unknown_incident() -> None:
    client = TestClient(create_app())
    response = client.post("/incidents/ghost/review", json={"decision": "approve"})
    assert response.status_code == 404


def test_audit_endpoint_returns_events() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-audit/replay", json={"scenario": "infeasible_reroute"})
    body = client.get("/audit/incident-audit").json()
    assert len(body["events"]) >= 8
    assert body["events"][0]["node"] == "observe"


def test_dashboard_is_served() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "CivicRipple" in response.text and "On watch" in response.text
    assert "text/html" in response.headers["content-type"]


def test_static_assets_served() -> None:
    client = TestClient(create_app())
    js = client.get("/static/app.js")
    css = client.get("/static/styles.css")
    assert js.status_code == 200 and "L.map" in js.text
    assert css.status_code == 200


def test_whatif_endpoint_returns_engine_result() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-wi/replay", json={"scenario": "infeasible_reroute"})
    response = client.post(
        "/incidents/incident-wi/whatif",
        json={"action": "drop_stop", "stop_id": "stop-b2"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["classification"] == "AUTO_RESOLVABLE"
    assert "stop-b2" in body["explanation"] or "drop stop" in body["explanation"]


def test_whatif_endpoint_409_without_context() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-wi-none/replay", json={"scenario": "no_impact"})
    response = client.post(
        "/incidents/incident-wi-none/whatif",
        json={"action": "delay_departure", "seconds": 600},
    )
    assert response.status_code == 409


def test_whatif_unknown_stop_is_400() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-wi2/replay", json={"scenario": "infeasible_reroute"})
    response = client.post(
        "/incidents/incident-wi2/whatif",
        json={"action": "drop_stop", "stop_id": "stop-zzz"},
    )
    assert response.status_code == 400


def test_review_with_variant_resolves_and_audits() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-wv/replay", json={"scenario": "infeasible_reroute"})
    response = client.post(
        "/incidents/incident-wv/review",
        json={
            "decision": "approve",
            "note": "recipient agreed",
            "variant": {
                "action": "shift_window",
                "stop_id": "stop-b2",
                "new_end": "2026-09-03T10:15:00Z",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "RESOLVED"
    assert response.json()["applied_variant"]["action"] == "shift_window"
    events = client.get("/audit/incident-wv").json()["events"]
    review_events = [e for e in events if e["node"] == "review"]
    assert any("variant" in e["facts"] for e in review_events)


def test_review_with_infeasible_variant_is_409() -> None:
    client = TestClient(create_app())
    client.post("/incidents/incident-wv2/replay", json={"scenario": "infeasible_reroute"})
    response = client.post(
        "/incidents/incident-wv2/review",
        json={
            "decision": "approve",
            "variant": {"action": "delay_departure", "seconds": 600},
        },
    )
    assert response.status_code == 409


def test_watch_endpoint_shape() -> None:
    client = TestClient(create_app())
    body = client.get("/watch").json()
    assert body["enabled"] is False  # not enabled in tests
    assert body["watching"].endswith("rss.xml")
    assert body["items"] == []


def test_report_counts() -> None:
    client = TestClient(create_app())
    client.post("/incidents/report-a/replay", json={"scenario": "feasible_reroute"})
    client.post("/incidents/report-b/replay", json={"scenario": "infeasible_reroute"})
    client.post(
        "/incidents/report-b/review",
        json={
            "decision": "approve",
            "variant": {"action": "drop_stop", "stop_id": "stop-b2"},
        },
    )
    body = client.get("/report").json()
    assert body["watched"] >= 2
    assert body["auto_resolved"] >= 1
    assert body["resolved_by_human"] >= 1
    assert body["false_interventions"] == 0
