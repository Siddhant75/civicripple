# Agent decision gates

Every action CivicRipple takes passes through fixed, testable gates. The
agents (LLMs) never hold operational authority; they interpret reality and
explain consequences. These gates decide.

## The three outcomes

| Classification | Meaning | Who acts |
|---|---|---|
| `NO_IMPACT` | The notice does not touch any planned leg (in time AND space) | Nobody — recorded, operation untouched |
| `AUTO_RESOLVABLE` | Safe detour exists, every hard delivery window still holds | The agent applies the internal reroute |
| `HUMAN_DECISION_REQUIRED` | Anything else: unproven avoidance, a broken promise, missing geometry, unverified source | The coordinator, with evidence prepared |

## Gate 1 — Verification gate

Before impact is even computed, the evidence verifier checks the notice's
authority. Synthetic/simulation sources are judged honestly (a well-formed
municipal notice passes; fabricated claims do not). An unverified notice
escalates to review — it is never silently trusted.

## Gate 2 — Impact gate (deterministic)

A leg is "affected" only when BOTH hold (half-open interval overlap in time,
Shapely intersection in space). No overlap → no impact, zero interruption.
No LLM is involved in this calculation.

## Gate 3 — Avoidance gate (two independent mechanisms)

A routing provider's detour is trusted only when BOTH pass:

1. the provider reports no avoidance violation (its notices are parsed; an
   avoidance-violation notice rejects the candidate outright), AND
2. independent local geometry (Shapely) proves the detour does not intersect
   the closure polygon.

Failing either rejects the candidate → human review (`ROUTE_AVOIDANCE_UNPROVEN`).
The agent never invents a route, and a missing route is escalated
(`ROUTING_UNAVAILABLE`), never improvised.

## Gate 4 — Feasibility gate (deterministic)

Arrival times are re-propagated over the detour (proportional duration
spreading, service durations honored). Every hard delivery window is
checked; `arrival > window end` is a violation (arrival exactly at the end
is allowed). Any violation → human review
(`HARD_CONSTRAINT_VIOLATION`) naming the stop and the lateness in seconds.

## Gate 5 — Policy gate (fail-closed classification)

Ordered rules; the first match wins:

1. no affected legs → `NO_IMPACT`
2. no candidate → review, `ROUTING_UNAVAILABLE`
3. avoidance unproven → review, `ROUTE_AVOIDANCE_UNPROVEN`
4. any hard-window violation → review, `HARD_CONSTRAINT_VIOLATION`
5. otherwise → `AUTO_RESOLVABLE`, permitted action `APPLY_INTERNAL_REROUTE`

## Gate 6 — Human review + the what-if console

A human-required incident can never auto-resolve; silence is never approval.
The coordinator sees the affected stops, the exact failed constraints, and
bounded options — and can negotiate through the **what-if console**: "drop
this stop", "delay the departure", "shift this window". Each variant is
re-run through the SAME feasibility and policy engines (Gate 3–5): the
console shows the computed consequence before the human commits. An
infeasible variant is refused with the computed reasons; a variant that
passes every gate can be approved — the decision, the variant, and both
review transitions are audited.

## Gate 7 — Audit gate

Every state transition writes an append-only audit event: correlation id,
node, from-state, to-state, structured facts (never generated prose),
runtime mode. In cloud mode the ledger lives in DynamoDB; audit-persistence
failure fails closed — consequential actions never proceed un-audited.

## State machine

All transitions are validated against an explicit adjacency map (frozen in
`docs/architecture.md` §7); illegal transitions raise
`InvalidStateTransition`. Human-required incidents remain pending forever
until a human acts — they never expire into approval.
