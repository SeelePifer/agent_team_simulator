import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.live.grok import grok_api_key, load_env
from app.schemas import ExperimentRequest, ExperimentResponse, HealthResponse, Scenario
from app.service import create_experiment, get_experiment, live_is_busy, subscribe, unsubscribe
from app.simulation.scenarios import list_scenarios

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    load_env()
    configured = True
    try:
        grok_api_key()
    except Exception:
        configured = False
    return HealthResponse(grok_api_key_configured=configured, live_busy=live_is_busy())


@router.get("/scenarios", response_model=list[Scenario])
def scenarios() -> list[Scenario]:
    return list_scenarios()


@router.post("/experiments", response_model=ExperimentResponse)
async def post_experiment(request: ExperimentRequest) -> ExperimentResponse:
    return await create_experiment(request)


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
def read_experiment(experiment_id: str) -> ExperimentResponse:
    try:
        return get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc


@router.get("/experiments/{experiment_id}/events")
async def experiment_events(experiment_id: str) -> StreamingResponse:
    try:
        queue = subscribe(experiment_id)
        current = get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc

    async def stream():
        try:
            if current.status != "running":
                payload = {"type": "status", "status": current.status, "error": current.error}
                yield f"data: {json.dumps(payload)}\n\n"
                return
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") == "status":
                    return
        finally:
            unsubscribe(experiment_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
