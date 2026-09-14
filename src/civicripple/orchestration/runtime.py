"""AWS runtime assembly (MODE=aws).

Builds the fully-AWS component set — Bedrock-backed agents, Amazon Location
routing, DynamoDB audit/incident persistence — and wires the same Phase 2
graph around them. There is deliberately NO replay fallback here: MODE=aws
with missing configuration fails loudly, and MODE=local_replay never routes
through this module (replay assembly stays in the scenario harness).

Note on the civic source: the notice TEXT and operation plan still come
from replay fixtures in Phase 3 (live browser ingestion is out of scope);
what is real here is the model, the routing, and the persistence."""

from dataclasses import dataclass

import boto3
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.graph import Graph

from civicripple.agents.disruption_extractor import build_extractor_agent
from civicripple.agents.evidence_verifier import build_verifier_agent
from civicripple.agents.options_agent import build_options_agent
from civicripple.config import RuntimeMode, Settings
from civicripple.orchestration.graph import build_incident_graph
from civicripple.services.amazon_location import (
    AmazonLocationRoutingProvider,
    build_geo_routes_client,
)
from civicripple.services.audit import DynamoDbAuditTrail
from civicripple.services.civic_source import ReplayCivicSource
from civicripple.services.storage import DynamoDbIncidentStore


@dataclass
class AwsRuntime:
    extractor: Agent
    verifier: Agent
    options: Agent
    routing: AmazonLocationRoutingProvider
    trail: DynamoDbAuditTrail
    store: DynamoDbIncidentStore


def build_bedrock_model(settings: Settings) -> BedrockModel:
    return BedrockModel(
        model_id=settings.bedrock_model_id, region_name=settings.aws_region
    )


def build_aws_runtime(settings: Settings) -> AwsRuntime:
    if settings.mode is not RuntimeMode.AWS:
        raise RuntimeError(
            "build_aws_runtime is for MODE=aws only; local_replay assembly "
            "lives in the replay scenario harness (no silent fallback)"
        )
    settings.require_aws()
    model = build_bedrock_model(settings)
    geo_client = build_geo_routes_client(settings.aws_region)
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(settings.dynamodb_table)
    return AwsRuntime(
        extractor=build_extractor_agent(model),
        verifier=build_verifier_agent(model),
        options=build_options_agent(model),
        routing=AmazonLocationRoutingProvider(geo_client),
        trail=DynamoDbAuditTrail(table),
        store=DynamoDbIncidentStore(table),
    )


def build_aws_graph(settings: Settings, notice_name: str = "feasible_closure.txt") -> Graph:
    runtime = build_aws_runtime(settings)
    return build_incident_graph(
        extractor=runtime.extractor,
        verifier=runtime.verifier,
        options_agent=runtime.options,
        source=ReplayCivicSource(notice_name=notice_name),
        routing=runtime.routing,
        trail=runtime.trail,
        store=runtime.store,
    )
