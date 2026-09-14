"""FastAPI application factory. Wires the Phase 2/3 adapters into the HTTP
surface; the API never calls AWS directly."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from civicripple.api.routes_incidents import router as incidents_router
from civicripple.api.routes_operations import AppComponents, operations_router
from civicripple.api.routes_review import router as review_router
from civicripple.api.routes_watch import router as watch_router
from civicripple.config import get_settings
from civicripple.orchestration.watch import WATCH_URL, WatchLedger
from civicripple.services.audit import AuditTrail
from civicripple.services.storage import InMemoryIncidentStore


def create_app(settings=None, *, store=None, trail=None) -> FastAPI:
    watch_enabled = os.environ.get("WATCH_ENABLED") == "1"
    poll_seconds = int(os.environ.get("WATCH_POLL_SECONDS", "300"))
    watch_live = os.environ.get("WATCH_LIVE") == "1"

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if watch_enabled:
            from civicripple.orchestration.watch import start_watch

            task = start_watch(app, poll_seconds, watch_live)
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="CivicRipple", version="0.1.0", lifespan=lifespan)
    app.state.components = AppComponents(
        settings=settings or get_settings(),
        store=store if store is not None else InMemoryIncidentStore(),
        trail=trail if trail is not None else AuditTrail(),
    )
    app.state.watch_ledger = WatchLedger()
    app.state.watch_url = WATCH_URL
    app.state.watch_enabled = watch_enabled
    app.include_router(operations_router())
    app.include_router(incidents_router)
    app.include_router(review_router)
    app.include_router(watch_router)

    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def dashboard():
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
