"""Incident read endpoints and replay control."""

from fastapi import APIRouter, Body, Path as PathParam, Request
from fastapi.responses import JSONResponse

from civicripple.api.routes_operations import AppComponents
from civicripple.orchestration.replay import run_replay_scenario
from civicripple.services.agentcore_proxy import invoke_cloud_scenario

router = APIRouter()

# Server-side constraint: correlation ids render in the dashboard and flow
# into DynamoDB keys — keep them to a safe alphabet (also closes stored-XSS
# via path-supplied ids).
CorrelationId = PathParam(..., pattern=r"^[A-Za-z0-9_-]{3,64}$", title="Correlation ID")


def _components(request: Request) -> AppComponents:
    return request.app.state.components


@router.get("/incidents")
def list_incidents(request: Request):
    components = _components(request)
    records = sorted(components.store.list(), key=lambda r: r.updated_at, reverse=True)
    return {"incidents": [r.model_dump(mode="json") for r in records]}


@router.get("/incidents/{correlation_id}")
def incident_detail(correlation_id: str = CorrelationId, request: Request = None):
    record = _components(request).store.get(correlation_id)
    if record is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return record.model_dump(mode="json")


@router.post("/incidents/{correlation_id}/replay")
def replay_incident(
    correlation_id: str = CorrelationId,
    request: Request = None,
    scenario: str = Body(..., embed=True),
    live: bool = Body(False, embed=True),
    remote: bool = Body(False, embed=True),
):
    components = _components(request)
    if remote:
        # Cloud path: the deployed AgentCore runtime does the whole run
        # (real Bedrock/Location/DynamoDB on its side); we persist and
        # serve the returned record. Fail loud on proxy errors.
        try:
            record = invoke_cloud_scenario(scenario, correlation_id)
        except KeyError:
            return JSONResponse(
                status_code=400,
                content={"detail": f"unknown scenario {scenario}"},
            )
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content={"detail": f"cloud run failed: {exc}"},
            )
        components.store.save(record)
        return record.model_dump(mode="json")
    try:
        run = run_replay_scenario(
            scenario,
            store=components.store,
            trail=components.trail,
            correlation_id=correlation_id,
            live=live,
        )
    except KeyError:
        return JSONResponse(
            status_code=400, content={"detail": f"unknown scenario {scenario}"}
        )
    except Exception as exc:  # explicit boundary: live model failure -> 502,
        # never a silent fallback to scripted replay
        return JSONResponse(
            status_code=502, content={"detail": f"live run failed: {exc}"}
        )
    # Live runs persist into their own (DynamoDB) store/trail — mirror the
    # record AND the audit events into the app listing so the dashboard
    # (list, map, run viewer, audit view) shows them.
    record = run.store.get(correlation_id) or components.store.get(correlation_id)
    components.store.save(record)
    for event in run.trail.events_for(correlation_id):
        try:
            components.trail.record(event)
        except ValueError:
            pass  # already mirrored (idempotent re-run)
    return record.model_dump(mode="json")
