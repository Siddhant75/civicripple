"""Local replay scenario runner.

Assembles the full replay stack (scripted agents, replay source/routing,
audit trail, incident store) from the scenario manifest and runs the
Phase 2 Strands graph. Shared by the test suite and the demo API."""

import json
from dataclasses import dataclass
from pathlib import Path

from strands.models import BedrockModel
from strands.multiagent.base import Status

from civicripple.agents.disruption_extractor import build_extractor_agent
from civicripple.agents.evidence_verifier import build_verifier_agent
from civicripple.agents.options_agent import build_options_agent
from civicripple.domain.models import (
    DisruptionEventCandidate,
    OptionsReport,
    VerificationVerdict,
)
from civicripple.orchestration.context import CONTEXT_KEY, IncidentContext
from civicripple.orchestration.graph import build_incident_graph
from civicripple.services.audit import AuditTrail
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.replay_model import ReplayModel
from civicripple.services.routing import ReplayRoutingProvider
from civicripple.services.storage import InMemoryIncidentStore

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class ReplayRun:
    ctx: IncidentContext
    trail: AuditTrail
    store: InMemoryIncidentStore


def _scenario(key: str) -> dict:
    return json.loads((FIXTURES / "scenarios.json").read_text())[key]


def aws_settings() -> tuple[str, str]:
    """Region + model id for live runs (read fresh; tests monkeypatch this)."""
    from civicripple.config import get_settings

    settings = get_settings()
    return settings.aws_region, settings.bedrock_model_id


def _build_live_infra():
    """Real Amazon Location routing + DynamoDB persistence for live runs.

    Monkeypatched in tests; in production returns the Phase 3 adapters
    configured from settings."""
    from civicripple.config import Settings
    from civicripple.orchestration.runtime import build_bedrock_model  # noqa: F401
    from civicripple.services.amazon_location import (
        AmazonLocationRoutingProvider,
        build_geo_routes_client,
    )
    from civicripple.services.audit import DynamoDbAuditTrail
    from civicripple.services.storage import DynamoDbIncidentStore

    import boto3

    from civicripple.config import get_settings

    settings = get_settings()
    geo_client = build_geo_routes_client(settings.aws_region)
    table = boto3.resource(
        "dynamodb", region_name=settings.aws_region
    ).Table(settings.dynamodb_table)
    return (
        AmazonLocationRoutingProvider(geo_client),
        DynamoDbAuditTrail(table),
        DynamoDbIncidentStore(table),
    )


def _build_live_agents():
    """Build the three agents on real Bedrock (live demo mode)."""
    from civicripple.agents.disruption_extractor import build_extractor_agent
    from civicripple.agents.evidence_verifier import build_verifier_agent
    from civicripple.agents.options_agent import build_options_agent
    from civicripple.config import Settings
    from civicripple.orchestration.runtime import build_bedrock_model

    region, model_id = aws_settings()
    model = build_bedrock_model(
        Settings(mode="aws", aws_region=region, bedrock_model_id=model_id)
    )
    return (
        build_extractor_agent(model),
        build_verifier_agent(model),
        build_options_agent(model),
    )


def run_replay_scenario(
    scenario_key: str,
    *,
    store: InMemoryIncidentStore | None = None,
    trail: AuditTrail | None = None,
    correlation_id: str | None = None,
    live: bool = False,
    notice_text: str | None = None,
    source_url_override: str | None = None,
    geocode_first: bool = False,
) -> ReplayRun:
    item = _scenario(scenario_key)
    replays = FIXTURES / "model_replays" / scenario_key
    if live:
        extractor, verifier, options_agent = _build_live_agents()
        routing, trail, store = _build_live_infra()
    else:
        extractor = build_extractor_agent(
            ReplayModel(
                [DisruptionEventCandidate.model_validate_json((replays / "extractor.json").read_text())]
            )
        )
        verifier = build_verifier_agent(
            ReplayModel([VerificationVerdict.model_validate_json((replays / "verifier.json").read_text())])
        )
        if (replays / "options.json").exists():
            options_agent = build_options_agent(
                ReplayModel([OptionsReport.model_validate_json((replays / "options.json").read_text())])
            )
        else:
            options_agent = build_options_agent(ReplayModel([]))
    if not live:
        candidate_name = (
            Path(item["route_candidate"]).name
            if item["route_candidate"]
            else "feasible.json"
        )
        routing = ReplayRoutingProvider(candidate_name=candidate_name)
        trail = trail if trail is not None else AuditTrail()
        store = store if store is not None else InMemoryIncidentStore()
    graph = build_incident_graph(
        extractor=extractor,
        verifier=verifier,
        options_agent=options_agent,
        source=ReplayCivicSource(notice_name=item["notice_text"]),
        routing=routing,
        trail=trail,
        store=store,
    )
    ctx = IncidentContext(
        correlation_id=correlation_id or f"incident-replay-{scenario_key}",
        mode="aws" if live else "local_replay",
        source_url=source_url_override or item["source_url"],
    )
    if notice_text is not None:
        ctx = ctx.model_copy(update={"notice_text": notice_text})
    if geocode_first:
        ctx = ctx.model_copy(update={"geocode_first": True})
    state = {CONTEXT_KEY: ctx}
    result = graph("process civic disruption incident", invocation_state=state)
    if result.status is not Status.COMPLETED:
        raise RuntimeError(f"replay scenario {scenario_key} failed: {result.status}")
    return ReplayRun(ctx=state[CONTEXT_KEY], trail=trail, store=store)
