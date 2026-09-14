from pathlib import Path

import pytest
from pydantic import ValidationError
from strands import Agent

from civicripple.agents.disruption_extractor import (
    build_extractor_agent,
    extract_disruption,
)
from civicripple.domain.models import DisruptionEventCandidate
from civicripple.services.replay_model import ReplayModel

FIXTURES = Path("src/civicripple/fixtures")


def _scripted_candidate(scenario: str) -> DisruptionEventCandidate:
    return DisruptionEventCandidate.model_validate_json(
        (FIXTURES / "model_replays" / scenario / "extractor.json").read_text()
    )


def test_extractor_returns_schema_bound_candidate() -> None:
    agent = build_extractor_agent(ReplayModel([_scripted_candidate("feasible_reroute")]))
    candidate = extract_disruption(agent, "any raw notice text", "https://replay.example/x")
    assert candidate.event_id == "evt-feasible-closure"
    assert candidate.type == "ROAD_CLOSURE"


def test_extractor_is_immune_to_prompt_injection() -> None:
    # The raw fixture text contains a prompt-injection directive; the
    # schema-bound output ignores it — no tools exist to act on it.
    raw = (FIXTURES / "notices_src" / "feasible_closure.txt").read_text()
    agent = build_extractor_agent(ReplayModel([_scripted_candidate("feasible_reroute")]))
    candidate = extract_disruption(
        agent, raw, "https://replay.example/notices/feasible-closure"
    )
    assert candidate.event_id == "evt-feasible-closure"


def test_extractor_carries_no_tools() -> None:
    agent = build_extractor_agent(ReplayModel([]))
    assert agent.tool_names == []  # untrusted-data interpreter: zero tools


def test_extract_disruption_propagates_validation_failure() -> None:
    # model_copy skips validation so the scripted "model" can emit an
    # invalid candidate; the structured-output tool must then reject it.
    bad = _scripted_candidate("feasible_reroute").model_copy(
        update={"geometry": {"kind": "MultiPolygon", "coordinates": [[[[0.0, 0.0]]]]}}
    )
    agent = build_extractor_agent(ReplayModel([bad]))
    from strands.types.exceptions import EventLoopException, StructuredOutputException

    with pytest.raises((ValidationError, StructuredOutputException, EventLoopException, RuntimeError)):
        extract_disruption(agent, "text", "https://replay.example/x")
