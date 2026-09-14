"""CivicRipple agent on AgentCore Runtime.

One invocation = one acceptance scenario processed end-to-end by the real
Strands graph with real Bedrock, Amazon Location, and DynamoDB."""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context=None):
    scenario = payload.get("scenario")
    if not isinstance(scenario, str) or not scenario:
        raise ValueError("payload must include a non-empty 'scenario' string")
    correlation_id = payload.get("correlation_id")
    if not isinstance(correlation_id, str) or len(correlation_id) < 3:
        raise ValueError("payload must include a 'correlation_id' string (>=3 chars)")

    from civicripple.orchestration.replay import run_replay_scenario

    run = run_replay_scenario(
        scenario,
        live=True,
        correlation_id=correlation_id,
    )
    record = run.store.get(correlation_id)
    return record.model_dump(mode="json")


if __name__ == "__main__":
    app.run()
