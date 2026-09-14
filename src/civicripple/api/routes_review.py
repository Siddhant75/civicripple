"""Human review action, what-if console, and audit trail reads.

Review decisions are explicit human actions: they run through the frozen
state machine and are audited. What-if variants are re-run through the
deterministic engines — the human sees computed consequences, and a chosen
variant must pass the identical policy gate before it can be applied.
Silence is never approval."""

import threading
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Path as PathParam, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from civicripple.api.routes_operations import AppComponents
from civicripple.domain.enums import IncidentState
from civicripple.domain.errors import InvalidStateTransition
from civicripple.domain.models import WhatIfVariant
from civicripple.orchestration.state import transition
from civicripple.services.audit import audit_transition
from civicripple.services.whatif import evaluate_variant

router = APIRouter()

CorrelationId = PathParam(..., pattern=r"^[A-Za-z0-9_-]{3,64}$", title="Correlation ID")


class ReviewRequest(BaseModel):
    decision: str  # "approve" | "reject"
    note: str | None = None
    variant: WhatIfVariant | None = None


def _components(request: Request) -> AppComponents:
    return request.app.state.components


# Serializes the read-validate-audit-save sequence per process: sync handlers
# run in a threadpool, and a double "Approve" click would otherwise race.
_review_lock = threading.Lock()


@router.post("/incidents/{correlation_id}/review")
def review(
    correlation_id: str = CorrelationId,
    body: ReviewRequest = Body(...),
    request: Request = None,
):
    components = _components(request)
    with _review_lock:
        return _review_locked(components, correlation_id, body)


def _review_locked(components, correlation_id: str, body: ReviewRequest):
    record = components.store.get(correlation_id)
    if record is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    if record.state is not IncidentState.REVIEW_REQUIRED:
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    f"incident state is {record.state.value}; "
                    "review requires REVIEW_REQUIRED"
                )
            },
        )
    if body.decision == "approve":
        first, second = IncidentState.HUMAN_APPROVED, IncidentState.RESOLVED
    elif body.decision == "reject":
        first, second = IncidentState.HUMAN_REJECTED, IncidentState.OPEN
    else:
        return JSONResponse(
            status_code=400, content={"detail": "decision must be approve or reject"}
        )

    permitted = "APPLY_INTERNAL_REROUTE"
    variant_facts: dict = {}
    if body.decision == "approve" and body.variant is not None:
        ctx = record.whatif_context
        if ctx is None or ctx.candidate is None:
            return JSONResponse(
                status_code=409, content={"detail": "no route candidate to vary"}
            )
        result = evaluate_variant(ctx.plan, ctx.route_id, ctx.candidate, body.variant)
        if not result.feasibility.feasible:
            return JSONResponse(
                status_code=409,
                content={"detail": f"variant still infeasible: {result.explanation}"},
            )
        permitted = "APPLY_INTERNAL_REROUTE_VARIANT"
        import json as _json

        variant_facts = {
            "variant": _json.dumps(
                body.variant.model_dump(mode="json"), separators=(",", ":")
            ),
            "variant_result": result.decision.classification.value,
        }

    facts = {"review": body.decision, "permitted_action": permitted, **variant_facts}
    if body.note is not None:
        facts["note"] = body.note
    try:
        transition(record.state, first)
        audit_transition(
            components.trail,
            correlation_id,
            "review",
            record.state,
            first,
            facts,
            components.settings.mode.value,
        )
        transition(first, second)
        audit_transition(
            components.trail,
            correlation_id,
            "review",
            first,
            second,
            facts,
            components.settings.mode.value,
        )
    except InvalidStateTransition as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    record = record.model_copy(
        update={
            "state": second,
            "updated_at": datetime.now(UTC),
            "applied_variant": body.variant,
        }
    )
    components.store.save(record)
    return record.model_dump(mode="json")


@router.post("/incidents/{correlation_id}/whatif")
def whatif(
    correlation_id: str = CorrelationId,
    body: WhatIfVariant = Body(...),
    request: Request = None,
):
    components = _components(request)
    record = components.store.get(correlation_id)
    if record is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    ctx = record.whatif_context
    if ctx is None or ctx.candidate is None:
        return JSONResponse(
            status_code=409,
            content={"detail": "incident has no route candidate to vary"},
        )
    try:
        result = evaluate_variant(ctx.plan, ctx.route_id, ctx.candidate, body)
    except KeyError:
        return JSONResponse(status_code=400, content={"detail": "unknown stop"})
    return result.model_dump(mode="json")


@router.get("/audit/{correlation_id}")
def audit_trail(correlation_id: str = CorrelationId, request: Request = None):
    components = _components(request)
    events = components.trail.events_for(correlation_id)
    if not events:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return {"events": [e.model_dump(mode="json") for e in events]}
