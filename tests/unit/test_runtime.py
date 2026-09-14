import pytest

from civicripple.config import RuntimeMode, Settings
from civicripple.orchestration.runtime import (
    AwsRuntime,
    build_aws_graph,
    build_aws_runtime,
    build_bedrock_model,
)
from civicripple.services.amazon_location import AmazonLocationRoutingProvider
from civicripple.services.audit import DynamoDbAuditTrail
from civicripple.services.storage import DynamoDbIncidentStore


def test_bedrock_model_built_without_any_call() -> None:
    model = build_bedrock_model(Settings())
    assert model is not None  # construction is offline; no AWS call happens


def test_build_aws_runtime_fails_closed_on_bad_settings(monkeypatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("DYNAMODB_TABLE", "")
    settings = Settings(mode="aws")
    with pytest.raises(RuntimeError, match="DYNAMODB_TABLE"):
        build_aws_runtime(settings)


def test_build_aws_runtime_components_are_aws_adapters() -> None:
    runtime = build_aws_runtime(Settings(mode="aws"))
    assert isinstance(runtime, AwsRuntime)
    assert isinstance(runtime.routing, AmazonLocationRoutingProvider)
    assert isinstance(runtime.trail, DynamoDbAuditTrail)
    assert isinstance(runtime.store, DynamoDbIncidentStore)
    assert runtime.extractor is not runtime.verifier  # three distinct agents


def test_build_aws_graph_returns_wired_graph() -> None:
    graph = build_aws_graph(Settings(mode="aws"))
    assert graph is not None
    node_ids = set(graph.nodes.keys())
    assert {
        "observe",
        "extract",
        "verify",
        "impact",
        "route",
        "geometry_validate",
        "feasibility",
        "policy",
        "options",
        "audit",
    } <= node_ids


def test_replay_mode_never_builds_aws_runtime() -> None:
    settings = Settings(mode=RuntimeMode.LOCAL_REPLAY)
    # There is intentionally no replay path through build_aws_runtime:
    # replay assembly stays in the scenario harness. Constructing AWS
    # components in replay mode is a programming error, not a fallback.
    with pytest.raises(RuntimeError):
        build_aws_runtime(settings)
