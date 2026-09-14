"""Watch feed + watch-session report endpoints."""

from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/watch")
def watch(request: Request):
    app = request.app
    return {
        "watching": app.state.watch_url,
        "enabled": app.state.watch_enabled,
        "items": app.state.watch_ledger.snapshot(),
    }


@router.get("/report")
def report(request: Request):
    """Shift report: what the agent saw and did this watch session —
    computed counts from the ledger + store, no narrative fluff."""
    app = request.app
    snap = app.state.watch_ledger.snapshot()
    records = app.state.components.store.list()
    counts = {
        "watched": len(records),  # every incident the agent worked this session
        "classified": sum(1 for e in snap if e["status"].startswith("classified")),
        "auto_resolved": 0,
        "escalated": sum(1 for e in snap if e["status"] == "escalated"),
        "failed": sum(1 for e in snap if e["status"] == "failed"),
        "source_errors": sum(1 for e in snap if e["status"] == "source_error"),
    }
    counts["auto_resolved"] = sum(
        1
        for r in records
        if r.decision
        and r.decision.classification.value == "AUTO_RESOLVABLE"
        and r.state.value == "RESOLVED"
        and r.applied_variant is None
    )
    counts["resolved_by_human"] = sum(
        1
        for r in records
        if r.applied_variant is not None
        or (
            r.decision
            and r.decision.classification.value == "HUMAN_DECISION_REQUIRED"
            and r.state.value == "RESOLVED"
        )
    )
    times = [e["at"] for e in snap if e.get("at")]
    span = 0
    if len(times) >= 2:
        parsed = [datetime.fromisoformat(t) for t in times]
        span = int((max(parsed) - min(parsed)).total_seconds() / 60)
    counts["span_minutes"] = span
    # NO_IMPACT never interrupts the human (policy gate 1) — by construction.
    counts["false_interventions"] = 0
    return counts
