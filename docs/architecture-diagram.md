# CivicRipple Architecture

Render the mermaid blocks below (GitHub renders them natively). PNG exports
for the submission are generated with `scripts/render_diagrams.py`.

## System flow (submission diagram)

```mermaid
flowchart TB
    subgraph Sources
        FEED["Real municipal feed<br/>WSDOT RSS (wsdot.wa.gov)"]
        FIXTURES["Replay fixtures<br/>(offline fallback + scenarios)"]
        CACHE["Feed cache<br/>(real data, offline replay)"]
    end

    USER[Food-bank coordinator] -->|reviews, approves, rejects| DASH["Web dashboard<br/>On watch / Today / Incident / Map / Audit"]
    DASH -->|JSON REST| API[FastAPI backend]

    subgraph AgentCore["AWS Bedrock AgentCore Runtime (deployed)"]
        AC["Cloud agent entrypoint<br/>live scenario runs"]
    end

    API -->|replay: scripted / live / cloud| GRAPH

    subgraph WATCHLOOP["On Watch — background poller"]
        POLL["Poll feed (2 min)<br/>dedupe by link hash"]
        GEOCODE["Bounded geocoder<br/>road name -> approximate corridor<br/>(deterministic index; unmatched escalates)"]
        LEDGER["Watch ledger<br/>observed / extracting /<br/>classified / escalated"]
        REPORT["Shift report<br/>counts: worked, auto-resolved,<br/>escalated, 0 false alarms"]
    end

    subgraph GRAPH["Strands Agents orchestration graph"]
        OBSERVE[Observe] --> EXTRACT["Extract agent<br/>schema-bound candidate, no tools<br/>(geocoder fallback for geometry)"]
        EXTRACT --> VERIFY["Verify agent<br/>authority + evidence verdict"]
        VERIFY --> IMPACT["Impact node<br/>deterministic: time AND space"]
        IMPACT -->|no overlap| AUDIT[Audit node]
        IMPACT -->|affected| ROUTE["Route node<br/>routing provider"]
        ROUTE --> GEO["Geometry validate<br/>independent Shapely check"]
        GEO -->|clear| FEAS["Feasibility node<br/>hard time windows"]
        GEO -->|unsafe| POLICY
        FEAS --> POLICY["Policy node<br/>fail-closed classification"]
        POLICY -->|AUTO_RESOLVABLE| AUDIT
        POLICY -->|HUMAN_DECISION_REQUIRED| OPTIONS["What-if console + options<br/>variants re-run the real engines"]
        OPTIONS --> AUDIT
    end

    FEED --> POLL
    POLL --> CACHE
    CACHE -->|offline| POLL
    POLL --> GEOCODE
    GEOCODE --> EXTRACT
    GEOCODE --> LEDGER
    LEDGER --> REPORT
    LEDGER -->|live activity| DASH
    FIXTURES --> OBSERVE

    subgraph AWS["AWS services"]
        BEDROCK[Amazon Bedrock<br/>Claude Sonnet 4.6]
        GEOLOC[Amazon Location Routes<br/>avoidance]
        DDB[("DynamoDB<br/>incidents + audit ledger")]
    end

    EXTRACT -.-> BEDROCK
    VERIFY -.-> BEDROCK
    OPTIONS -.-> BEDROCK
    ROUTE -.-> GEOLOC
    AUDIT -.-> DDB
    AC --> GRAPH

    API -->|SigV4 InvokeAgentRuntime| AC
    AUDIT -->|state transitions + structured facts| DASH
```

## The two-graph separation (core thesis)

```mermaid
flowchart TB
    subgraph Domain["Domain dependency graph (typed data, zero LLM)"]
        OP[OperationPlan] --> R[Routes] --> L[Legs] --> S[Stops] --> TW[TimeWindows]
    end
    subgraph Orch["Strands orchestration graph"]
        A["Agents interpret reality<br/>(schema-bound, no tools)"] --> D["Deterministic nodes calculate impact<br/>(overlap, geometry, feasibility)"]
        D --> P["Policy decides<br/>(fail-closed gates)"]
        P -->|safe + permitted| AUTO[Auto-apply]
        P -->|unproven or infeasible| HUMAN["Human review with evidence,<br/>what-if console, bounded options"]
    end
    Orch -->|typed Pydantic contracts only| Domain
```

Key invariants: LLM output is never operational truth until schema-validated; geometry/feasibility/policy contain no LLM calls; provider avoidance is independently validated (provider notices AND local geometry); the LLM never invents geometry (deterministic corridor index or escalate); silence is never approval; every transition is audited with structured facts.
