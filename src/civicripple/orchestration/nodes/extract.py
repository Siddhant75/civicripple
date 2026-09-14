from datetime import UTC, datetime

from pydantic import ValidationError
from strands import Agent
from strands.types.exceptions import EventLoopException, StructuredOutputException

from civicripple.agents.disruption_extractor import extract_disruption
from civicripple.domain.enums import IncidentState, SourceKind
from civicripple.domain.models import DisruptionEvent, EvidenceFact
from civicripple.orchestration.context import IncidentContext
from civicripple.orchestration.nodes.base import DeterministicNode
from civicripple.services.audit import AuditTrail, audit_transition
from civicripple.services.geocode import GEOCODED_FACT, geocode_notice


def run(ctx: IncidentContext, extractor: Agent, trail: AuditTrail) -> IncidentContext:
    if ctx.notice_text is None or ctx.source_url is None:
        raise RuntimeError("extract: observe must run first (notice_text/source_url missing)")
    candidate = None
    disruption = None
    if not ctx.geocode_first:
        try:
            candidate = extract_disruption(extractor, ctx.notice_text, ctx.source_url)
            disruption = DisruptionEvent.model_validate(candidate.model_dump())
        except (
            ValidationError,
            StructuredOutputException,
            EventLoopException,
            RuntimeError,
            ValueError,
        ):
            disruption = None

    if disruption is None:
        # The model could not produce a usable geometry (or failed outright).
        # Before escalating, try the deterministic corridor index: a real
        # road name in the notice maps to an approximate real corridor.
        # The LLM never invents geometry; the index is grounded.
        corridor = geocode_notice(ctx.notice_text or "")
        if corridor is not None:
            fact = EvidenceFact(
                field="geometry_source",
                value=GEOCODED_FACT,
                source=ctx.source_url,
                source_kind=SourceKind.OFFICIAL_WEB,
                observed_at=datetime.now(UTC),
                excerpt_hash="geocode",
            )
            if candidate is not None:
                candidate = candidate.model_copy(
                    update={"geometry": corridor, "facts": [*candidate.facts, fact]}
                )
                try:
                    disruption = DisruptionEvent.model_validate(candidate.model_dump())
                except (ValidationError, ValueError):
                    disruption = None
            else:
                # No candidate at all: build the minimal event around the
                # corridor so the impact gate can still evaluate honestly.
                candidate = _minimal_candidate(ctx, corridor, fact)
                try:
                    disruption = DisruptionEvent.model_validate(candidate.model_dump())
                except (ValidationError, ValueError):
                    disruption = None

    if disruption is None:
        # LLM/extraction failure: preserve the plan, fail closed to review.
        audit_transition(
            trail,
            ctx.correlation_id,
            "extract",
            IncidentState.DETECTED,
            IncidentState.REVIEW_REQUIRED,
            {"failure": "EXTRACTION_FAILED"},
            ctx.mode,
        )
        return ctx.model_copy(
            update={"state": IncidentState.REVIEW_REQUIRED, "failure": "EXTRACTION_FAILED"}
        )

    facts = {
        "event_id": candidate.event_id,
        "disruption_type": candidate.type.value,
    }
    if any(f.field == "geometry_source" for f in candidate.facts):
        facts["geocoded"] = True
    audit_transition(
        trail,
        ctx.correlation_id,
        "extract",
        IncidentState.DETECTED,
        IncidentState.EXTRACTED,
        facts,
        ctx.mode,
    )
    return ctx.model_copy(
        update={
            "candidate": candidate,
            "disruption": disruption,
            "state": IncidentState.EXTRACTED,
        }
    )


def _minimal_candidate(ctx: IncidentContext, corridor, fact: EvidenceFact):
    import hashlib as _hl

    from civicripple.domain.models import DisruptionEventCandidate

    stable = _hl.sha256((ctx.source_url or "").encode()).hexdigest()[:10]
    return DisruptionEventCandidate(
        event_id=f"evt-geocoded-{stable}",
        type="ROAD_CLOSURE",
        authority="Washington State Department of Transportation",
        source_url=ctx.source_url,
        published_at=datetime.now(UTC),
        valid_from=datetime.now(UTC),
        valid_until=None,
        geometry=corridor,
        severity="MODERATE",
        facts=[fact],
        verification_status="UNVERIFIED",
    )


def make_extract_node(extractor: Agent, trail: AuditTrail) -> DeterministicNode:
    return DeterministicNode("extract", lambda ctx: run(ctx, extractor, trail))
