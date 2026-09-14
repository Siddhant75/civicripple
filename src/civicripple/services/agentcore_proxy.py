"""SigV4 proxy to the deployed CivicRipple AgentCore runtime.

The browser cannot call AgentCore directly (no public URL; SigV4 only),
so this backend module is the single AWS-calling hop for cloud replays.
Fail loud: missing configuration raises RuntimeError, never a silent
local fallback."""

import json
import os
import uuid
from pathlib import Path

from civicripple.domain.models import IncidentRecord

RUNTIME_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "infra"
    / "agentcore"
    / "runtime.json"
)


def _runtime_file_arn() -> str | None:
    try:
        return json.loads(RUNTIME_FILE.read_text())["agentRuntimeArn"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def _client():
    import boto3

    return boto3.client("bedrock-agentcore")


def invoke_cloud_scenario(scenario: str, correlation_id: str) -> IncidentRecord:
    arn = os.environ.get("AGENTCORE_RUNTIME_ARN") or _runtime_file_arn()
    if not arn:
        raise RuntimeError(
            "cloud replay requires AGENTCORE_RUNTIME_ARN "
            "(or infra/agentcore/runtime.json)"
        )
    client = _client()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(
            {"scenario": scenario, "correlation_id": correlation_id}
        ).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = b"".join(resp["response"]).decode()
    return IncidentRecord.model_validate_json(body)
