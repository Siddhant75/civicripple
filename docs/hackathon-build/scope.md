# CivicRipple — Hackathon Scope

**Hackathon:** Agents for Humans Hackathon 2026  
**Target track:** Good Neighbor Agents  
**Working project name:** CivicRipple  
**One-line pitch:** An autonomous community continuity agent that detects civic disruptions, determines which food-bank deliveries are actually affected, safely reroutes what it can, and interrupts a coordinator only when a real operational decision is required.

## 1. Problem statement

Small food banks and volunteer-led community organizations often operate without a dedicated operations center. A road closure, transit disruption, facility closure, or municipal notice may be published externally, but someone still has to notice it, determine whether it affects today's work, calculate an alternative, coordinate changes, and decide when service must be delayed or altered.

CivicRipple targets that unattended interval.

The MVP focuses on one concrete problem:

> Keep a small food bank's scheduled home-delivery operation running when an unexpected road closure affects today's routes.

## 2. Primary user

A volunteer operations coordinator at a small food bank or community meal-delivery organization.

The coordinator should not have to continuously watch municipal websites or manually recompute routes. CivicRipple operates in the background and surfaces only when a deterministic feasibility check shows that policy-safe automation cannot preserve the delivery plan.

## 3. MVP user story

Given:

- one distribution depot,
- 1–3 volunteer drivers,
- 8–20 scheduled delivery stops,
- delivery time windows,
- existing route order and geometry,
- one or more official civic-notice sources,

when a new civic notice describes a road closure, CivicRipple will:

1. detect or ingest the notice;
2. extract a typed `DisruptionEvent` with evidence;
3. verify that the notice is authoritative enough to evaluate;
4. deterministically test temporal and geospatial overlap against the operation plan;
5. request an alternate route that avoids the closure;
6. independently validate that the returned route does not cross the closure;
7. recompute arrival times and delivery-window feasibility;
8. classify the incident as `NO_IMPACT`, `AUTO_RESOLVABLE`, or `HUMAN_DECISION_REQUIRED`;
9. automatically apply policy-safe internal changes or surface a bounded decision to the coordinator;
10. persist an audit record explaining what happened and why.

## 4. Product promise

CivicRipple does **not** promise to make emergency-response decisions. It promises to remove the repetitive operational work between receiving a public disruption notice and knowing whether today's community service can continue safely.

## 5. Success criteria

The hackathon MVP is successful when all five acceptance scenarios pass:

### A. Irrelevant notice
A notice is extracted correctly but does not overlap any route in time and space. CivicRipple records it and takes no operational action.

### B. Relevant closure with feasible reroute
A closure intersects a route leg. CivicRipple finds a safe alternate route, all delivery time windows remain valid, and the incident is resolved without human intervention.

### C. Relevant closure with infeasible reroute
The alternate route causes at least one delivery-window violation. CivicRipple blocks automatic execution and requests human review.

### D. Avoidance failure
The routing provider returns a route even though avoidance could not be fully honored. CivicRipple independently detects intersection with the closed area and rejects the candidate route.

### E. Human decision
CivicRipple explains which stops are affected, which constraint failed, and presents a small set of bounded options without inventing or silently executing a consequential action.

## 6. Demo scenarios

The final demo should use three short incidents.

### Scenario 1 — Noise / no impact
A municipal notice or webpage change is unrelated to the food-bank routes. Result: `NO_IMPACT`.

### Scenario 2 — Autonomous continuity
A road closure affects one driver's route. A reroute adds modest travel time but preserves every delivery window. Result: `AUTO_RESOLVABLE`.

### Scenario 3 — Human judgment required
A closure makes several deliveries infeasible within their promised windows. CivicRipple prepares impact evidence and alternatives, then waits for the coordinator. Result: `HUMAN_DECISION_REQUIRED`.

## 7. In scope

- Python backend and Strands agent workflow.
- Typed operation-plan and disruption schemas.
- Scheduled/background execution path.
- Official/simulated civic-notice ingestion.
- Strands structured extraction of notices.
- Source/evidence validation.
- Temporal-overlap calculation.
- Geospatial route/closure intersection.
- Amazon Location rerouting with avoidance.
- Independent validation of candidate-route geometry.
- Delivery-window feasibility calculation.
- Risk/policy gate.
- Human-review queue.
- Audit/event ledger.
- Lightweight web dashboard suitable for the hackathon demo.
- Deterministic fixture/replay mode so the full demo works even if external municipal sources are unavailable.

## 8. Explicitly out of scope

These are deliberately cut from the hackathon MVP:

- general disaster management;
- emergency-services dispatch;
- autonomous safety/medical decisions;
- multi-city support;
- universal civic-data ingestion;
- arbitrary incident types beyond the small supported schema;
- full vehicle-routing optimization across the entire fleet;
- volunteer marketplace/recruitment;
- outbound voice calling;
- generalized CRM;
- real-time traffic prediction;
- public consumer mobile app;
- autonomous cancellation of service;
- autonomous venue changes;
- production-scale identity/tenancy/billing.

## 9. Supported disruption types

For the MVP, the internal schema should support multiple types, but only `ROAD_CLOSURE` must be end-to-end functional.

```text
ROAD_CLOSURE      <- required MVP path
FACILITY_CLOSURE  <- schema-ready, optional demo
TRANSIT_DISRUPTION
UTILITY_OUTAGE
WEATHER_NOTICE
OTHER
```

## 10. Safety and autonomy policy

### Agent may autonomously

- ingest public information;
- extract candidate facts;
- verify sources;
- calculate impact;
- request route alternatives;
- update an internal proposed route when all deterministic constraints pass;
- update audit state;
- mark an incident resolved when no external communication or service-level decision is needed.

### Agent may not autonomously

- cancel deliveries;
- change a distribution venue;
- remove a recipient from service;
- send mass external notifications;
- reassign a volunteer to a materially different commitment;
- make medical/safety judgments;
- bypass a failed deterministic constraint;
- treat LLM confidence as proof of operational feasibility.

Those actions require explicit human approval or remain outside the MVP.

## 11. Judge-facing measurable outcomes

- disruptions scanned;
- relevant disruptions detected;
- false-intervention count;
- impact-detection latency;
- deliveries protected;
- autonomous-resolution rate;
- human-interruption rate;
- added route minutes;
- unserved deliveries;
- rejected unsafe candidate routes;
- audit completeness.

## 12. Scope rule

If a proposed feature does not make one of the three demo scenarios more convincing, safer, or easier to judge, it does not enter the MVP.
