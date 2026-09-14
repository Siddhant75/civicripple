"""Health, mode visibility, and operation-plan read endpoints."""

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from civicripple.config import Settings
from civicripple.services.civic_source import ReplayCivicSource


@dataclass
class AppComponents:
    settings: Settings
    store: object  # IncidentStore-like (InMemory | DynamoDb)
    trail: object  # AuditTrail-like (InMemory | DynamoDb)

    @property
    def store_kind(self) -> str:
        return {
            "InMemoryIncidentStore": "in_memory",
            "DynamoDbIncidentStore": "dynamodb",
        }.get(type(self.store).__name__, "unknown")


def operations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @router.get("/mode")
    def mode(request: Request) -> dict:
        components: AppComponents = request.app.state.components
        return {
            "mode": components.settings.mode.value,
            "region": components.settings.aws_region,
            "store": components.store_kind,
        }

    @router.get("/operations/{operation_id}")
    def operation(operation_id: str, request: Request):
        if operation_id != "op-demo-2026-09-03":
            return JSONResponse(status_code=404, content={"detail": "not found"})
        plan = ReplayCivicSource(notice_name="no_impact.txt").load_plan()
        return plan.model_dump(mode="json")

    return router
