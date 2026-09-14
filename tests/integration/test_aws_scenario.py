"""One AWS-backed acceptance scenario (MVP-complete requirement): the
feasible-closure incident processed end-to-end with real Bedrock
extraction/verification, real Amazon Location routing, and DynamoDB audit
persistence."""

import uuid

import pytest
from strands.multiagent.base import Status

pytestmark = pytest.mark.aws_integration

from civicripple.config import Settings
from civicripple.domain.enums import DecisionClassification, IncidentState
from civicripple.orchestration.context import CONTEXT_KEY, IncidentContext
from civicripple.orchestration.runtime import build_aws_graph


def test_aws_backed_scenario_runs_end_to_end(disposable_table) -> None:
    settings = Settings(mode="aws")
    settings.dynamodb_table = disposable_table.table_name  # disposable table for the run
    graph = build_aws_graph(settings, notice_name="feasible_closure.txt")
    correlation_id = f"incident-aws-{uuid.uuid4()}"
    ctx = IncidentContext(
        correlation_id=correlation_id,
        mode="aws",
        source_url="https://notices.replayville.gov/2026/feasible-closure",
    )
    state = {CONTEXT_KEY: ctx}
    result = graph("process civic disruption incident", invocation_state=state)
    ctx = state[CONTEXT_KEY]

    # The full pipeline ran against real services and closed cleanly.
    assert result.status is Status.COMPLETED
    assert ctx.impact is not None and ctx.impact.affected_leg_ids == ["leg-b2"]
    assert ctx.decision is not None
    assert ctx.decision.classification in (
        DecisionClassification.AUTO_RESOLVABLE,
        DecisionClassification.HUMAN_DECISION_REQUIRED,
    )
    # Classification must be consistent with the deterministic feasibility
    # result on the real route duration — never optimistic.
    if ctx.feasibility is not None and not ctx.feasibility.feasible:
        assert ctx.decision.classification is DecisionClassification.HUMAN_DECISION_REQUIRED
        assert ctx.decision.review_reason == "HARD_CONSTRAINT_VIOLATION"
    if ctx.route_candidate is not None and not ctx.route_candidate.independently_clear_of_disruption:
        assert ctx.decision.review_reason == "ROUTE_AVOIDANCE_UNPROVEN"

    # Every transition was audited into DynamoDB, in state-machine order.
    from civicripple.services.audit import DynamoDbAuditTrail

    trail = DynamoDbAuditTrail(disposable_table)
    events = trail.events_for(correlation_id)
    assert len(events) >= 8
    states = [(e.state_from, e.state_to) for e in events]
    assert states[0] == (IncidentState.DETECTED, IncidentState.DETECTED)
    assert (IncidentState.VERIFIED, IncidentState.IMPACT_ASSESSED) in states
    assert all(e.mode == "aws" for e in events)

    # The incident record was persisted with the final state.
    from civicripple.services.storage import DynamoDbIncidentStore

    record = DynamoDbIncidentStore(disposable_table).get(correlation_id)
    assert record is not None
    assert record.state in (IncidentState.RESOLVED, IncidentState.REVIEW_REQUIRED)
