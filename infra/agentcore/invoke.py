"""Smoke-invoke the deployed CivicRipple agent.

Usage: uv run python infra/agentcore/invoke.py [scenario] [correlation_id]
"""

import json
import sys
import time
import uuid
from pathlib import Path

import boto3

HERE = Path(__file__).parent
runtime = json.loads((HERE / "runtime.json").read_text())

scenario = sys.argv[1] if len(sys.argv) > 1 else "feasible_reroute"
correlation_id = sys.argv[2] if len(sys.argv) > 2 else f"incident-cloud-{int(time.time())}"

session = boto3.Session(profile_name="civicripple-dev", region_name=runtime["region"])
client = session.client("bedrock-agentcore")
resp = client.invoke_agent_runtime(
    agentRuntimeArn=runtime["agentRuntimeArn"],
    runtimeSessionId=str(uuid.uuid4()),  # >= 33 chars
    payload=json.dumps({"scenario": scenario, "correlation_id": correlation_id}).encode(),
    contentType="application/json",
    accept="application/json",
)
body = b"".join(resp["response"]).decode()
record = json.loads(body)
print("correlation:", record["correlation_id"])
print("state:", record["state"])
print("decision:", record["decision"])
