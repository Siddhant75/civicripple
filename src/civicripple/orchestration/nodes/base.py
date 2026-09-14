"""DeterministicNode: a Strands graph node that runs pure typed logic.

The Strands graph passes only text between nodes; the typed IncidentContext
travels in the shared invocation_state dict. Each node also emits a text
summary AgentResult so the graph machinery can record/propagate results."""

from collections.abc import Callable

from strands.agent.agent_result import AgentResult
from strands.multiagent.base import (
    MultiAgentBase,
    MultiAgentResult,
    NodeResult,
    Status,
)
from strands.telemetry.metrics import EventLoopMetrics
from strands.types.content import ContentBlock, Message

from civicripple.orchestration.context import CONTEXT_KEY, IncidentContext


class DeterministicNode(MultiAgentBase):
    def __init__(
        self, name: str, run: Callable[[IncidentContext], IncidentContext]
    ) -> None:
        super().__init__()
        self.name = name
        self._run = run

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        state = invocation_state if invocation_state is not None else {}
        ctx = state.get(CONTEXT_KEY)
        if ctx is None:
            raise RuntimeError(f"node {self.name}: missing {CONTEXT_KEY} in invocation_state")
        ctx = self._run(ctx)
        state[CONTEXT_KEY] = ctx

        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=self._summary(ctx))]),
            metrics=EventLoopMetrics(),
            state={},
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.name: NodeResult(result=agent_result, status=Status.COMPLETED)},
        )

    @staticmethod
    def _summary(ctx: IncidentContext) -> str:
        parts = [f"incident={ctx.correlation_id}", f"state={ctx.state.value}"]
        if ctx.impact is not None:
            parts.append(f"affected_legs={ctx.impact.affected_leg_ids}")
        if ctx.decision is not None:
            parts.append(f"classification={ctx.decision.classification.value}")
        if ctx.failure is not None:
            parts.append(f"failure={ctx.failure}")
        return " ".join(parts)
