"""Scripted offline model for MODE=local_replay.

Adapted from the Strands SDK test fixture MockedModelProvider
(Apache-2.0, github.com/strands-agents/harness-sdk, tag python/v1.54.0,
strands-py/tests/fixtures/mocked_model_provider.py).

Plays back pre-recorded responses in order. A Pydantic response is emitted
as a toolUse block for the first advertised tool spec — which, for
CivicRipple agents, is always the structured-output tool (agents carry no
other tools). A plain string is emitted as an end_turn text block.
"""

from typing import Any

from pydantic import BaseModel
from strands.models import Model


class ReplayModel(Model):
    def __init__(self, responses: list[BaseModel | str]) -> None:
        self._responses: list[BaseModel | str] = list(responses)
        self._config: dict[str, Any] = {}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        # Structured output flows through stream() and the structured-output
        # tool spec; nothing to yield on this direct path.
        return
        yield  # pragma: no cover - makes this an async generator

    async def stream(
        self,
        messages,
        tool_specs: list | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice=None,
        system_prompt_content=None,
        invocation_state: dict | None = None,
        cancel_signal=None,
        **kwargs: Any,
    ):
        if not self._responses:
            raise RuntimeError("ReplayModel has no scripted response left")
        response = self._responses.pop(0)

        yield {"messageStart": {"role": "assistant"}}
        if isinstance(response, BaseModel) and tool_specs:
            tool_name = tool_specs[0]["name"]
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"name": tool_name, "toolUseId": "replay-tool-use-1"}}
                }
            }
            # The SDK's stream handler concatenates toolUse input deltas as
            # string chunks (like Bedrock's partial JSON streaming), so the
            # scripted payload must be emitted as a single JSON string.
            yield {
                "contentBlockDelta": {
                    "delta": {
                        "toolUse": {"input": response.model_dump_json()}
                    }
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": str(response)}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
