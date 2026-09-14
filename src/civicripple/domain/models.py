from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from civicripple.domain.enums import (
    DecisionClassification,
    DisruptionSeverity,
    DisruptionType,
    IncidentState,
    SourceKind,
    VerificationStatus,
)

GeoShapeKind = Literal["Point", "LineString", "Polygon"]


class LocationPoint(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class GeoShape(BaseModel):
    """GeoJSON-style geometry. Converted to Shapely only in services/geometry.py."""

    kind: GeoShapeKind
    coordinates: list  # JSON-compatible nested coordinate arrays; structure depends on kind

    @field_validator("kind", mode="before")
    @classmethod
    def _kind_is_supported(cls, value: str) -> str:
        supported = {"Point", "LineString", "Polygon"}
        if value not in supported:
            raise ValueError(f"unsupported geometry kind: {value!r}")
        return value


class TimeWindow(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _end_after_start(self) -> "TimeWindow":
        if self.end <= self.start:
            raise ValueError("time window end must be after start")
        return self


# --- Operation plan ---------------------------------------------------------


class DriverShift(BaseModel):
    shift_id: str
    driver_id: str
    start: datetime
    end: datetime


class DeliveryStop(BaseModel):
    stop_id: str
    location: LocationPoint
    service_duration_s: int = Field(default=0, ge=0)
    time_window: TimeWindow


class RouteLeg(BaseModel):
    leg_id: str
    from_stop_id: str
    to_stop_id: str
    geometry: GeoShape
    planned_departure: datetime
    planned_arrival: datetime
    duration_s: int = Field(ge=0)


class RoutePlan(BaseModel):
    route_id: str
    driver_id: str
    stops: list[DeliveryStop]
    legs: list[RouteLeg]


class OperationPlan(BaseModel):
    operation_id: str
    service_date: date
    depot: LocationPoint
    driver_shifts: list[DriverShift]
    routes: list[RoutePlan]


# --- Disruption evidence ----------------------------------------------------


class EvidenceFact(BaseModel):
    field: str
    value: str
    source: str
    source_kind: SourceKind
    observed_at: datetime
    excerpt_hash: str


class DisruptionEvent(BaseModel):
    event_id: str
    type: DisruptionType
    authority: str
    source_url: str | None = None
    published_at: datetime | None = None
    valid_from: datetime
    valid_until: datetime | None = None
    geometry: GeoShape
    severity: DisruptionSeverity
    facts: list[EvidenceFact]
    verification_status: VerificationStatus


# --- Deterministic outcomes -------------------------------------------------


class ImpactAssessment(BaseModel):
    disruption_id: str
    operation_id: str
    affected_route_ids: list[str]
    affected_leg_ids: list[str]
    affected_stop_ids: list[str]
    temporal_overlap: bool
    spatial_overlap: bool
    reasons: list[str]


class RouteCandidate(BaseModel):
    route_id: str
    provider: str
    geometry: GeoShape
    distance_m: int = Field(ge=0)
    duration_s: int = Field(ge=0)
    provider_notices: list[str]
    independently_clear_of_disruption: bool


class StopArrival(BaseModel):
    stop_id: str
    arrival_at: datetime


class ConstraintViolation(BaseModel):
    stop_id: str
    code: str
    message: str
    lateness_s: int = Field(default=0, ge=0)


class FeasibilityResult(BaseModel):
    feasible: bool
    stop_arrivals: list[StopArrival]
    violations: list[ConstraintViolation]
    added_duration_s: int


class IncidentDecision(BaseModel):
    classification: DecisionClassification
    permitted_action: str | None = None
    review_reason: str | None = None


class HumanReviewPayload(BaseModel):
    incident_id: str
    affected_stop_ids: list[str]
    failed_constraints: list[ConstraintViolation]
    reason: str


class MapStop(BaseModel):
    stop_id: str
    location: LocationPoint
    window_start: datetime
    window_end: datetime
    planned_arrival: datetime | None = None
    projected_arrival: datetime | None = None


class MapLeg(BaseModel):
    leg_id: str
    route_id: str
    coordinates: list[list[float]]
    affected: bool


class MapSnapshot(BaseModel):
    depot: LocationPoint
    stops: list[MapStop]
    legs: list[MapLeg]
    disruption_geometry: GeoShape | None = None
    candidate_geometry: GeoShape | None = None
    candidate_duration_s: int | None = None


# --- Phase 2: agent-bound and orchestration contracts -----------------------


class DisruptionEventCandidate(BaseModel):
    """Schema-bound extractor output. Distinct from DisruptionEvent:
    deterministic validation (not the agent) promotes a candidate to an event.
    """

    event_id: str
    type: DisruptionType
    authority: str
    source_url: str | None = None
    published_at: datetime | None = None
    valid_from: datetime
    valid_until: datetime | None = None
    geometry: GeoShape
    severity: DisruptionSeverity
    facts: list[EvidenceFact]
    verification_status: VerificationStatus


class VerificationVerdict(BaseModel):
    status: VerificationStatus
    authority: str
    reasons: list[str]


class BoundedOption(BaseModel):
    option_id: str
    title: str
    description: str
    requires_human_approval: bool


class OptionsReport(BaseModel):
    incident_id: str
    affected_stop_ids: list[str]
    summary: str
    options: list[BoundedOption]


class AuditEvent(BaseModel):
    """Append-only audit record. Structured facts only — never model prose."""

    event_id: str
    correlation_id: str
    node: str
    state_from: IncidentState
    state_to: IncidentState
    facts: dict[str, str | int | bool | list[str]]
    mode: str
    recorded_at: datetime


class WhatIfVariant(BaseModel):
    action: Literal["drop_stop", "delay_departure", "shift_window"]
    stop_id: str | None = None
    seconds: int | None = Field(default=None, ge=60, le=3600)
    new_end: datetime | None = None

    @model_validator(mode="after")
    def _require_action_fields(self) -> "WhatIfVariant":
        if self.action == "drop_stop" and not self.stop_id:
            raise ValueError("drop_stop requires stop_id")
        if self.action == "delay_departure" and self.seconds is None:
            raise ValueError("delay_departure requires seconds (60..3600)")
        if self.action == "shift_window":
            if not self.stop_id or self.new_end is None:
                raise ValueError("shift_window requires stop_id and new_end")
        return self


class WhatIfContext(BaseModel):
    plan: OperationPlan
    route_id: str
    candidate: RouteCandidate | None = None


class WhatIfResult(BaseModel):
    variant: WhatIfVariant
    feasibility: FeasibilityResult
    decision: IncidentDecision
    explanation: str


class IncidentRecord(BaseModel):
    correlation_id: str
    state: IncidentState
    decision: IncidentDecision | None = None
    review_payload: HumanReviewPayload | None = None
    options: OptionsReport | None = None
    map: MapSnapshot | None = None
    whatif_context: WhatIfContext | None = None
    applied_variant: WhatIfVariant | None = None
    created_at: datetime
    updated_at: datetime
