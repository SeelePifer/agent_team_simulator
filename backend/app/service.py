import asyncio
from uuid import uuid4

from fastapi import HTTPException

from app.live.runner import prepare_live_state, run_live
from app.schemas import ExperimentRequest, ExperimentResponse, RunMetrics, Strategy
from app.simulation.engine import run_simulation
from app.simulation.metrics import summarize
from app.simulation.scenarios import get_scenario

EXPERIMENTS: dict[str, ExperimentResponse] = {}
SUBSCRIBERS: dict[str, list[asyncio.Queue]] = {}
LIVE_LOCK = asyncio.Lock()
STRATEGIES: tuple[Strategy, ...] = ("sequential", "parallel", "supervisor")


async def create_experiment(request: ExperimentRequest) -> ExperimentResponse:
    scenario = _scenario_or_404(request.scenario_id)
    if request.mode == "live":
        return await _start_live(request, scenario.failure_rate)
    experiment = _simulate(request)
    EXPERIMENTS[experiment.id] = experiment
    return experiment


def get_experiment(experiment_id: str) -> ExperimentResponse:
    try:
        return EXPERIMENTS[experiment_id].model_copy(deep=True)
    except KeyError as exc:
        raise KeyError(experiment_id) from exc


def subscribe(experiment_id: str) -> asyncio.Queue:
    if experiment_id not in EXPERIMENTS:
        raise KeyError(experiment_id)
    queue: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS.setdefault(experiment_id, []).append(queue)
    return queue


def unsubscribe(experiment_id: str, queue: asyncio.Queue) -> None:
    listeners = SUBSCRIBERS.get(experiment_id, [])
    if queue in listeners:
        listeners.remove(queue)


def live_is_busy() -> bool:
    return LIVE_LOCK.locked()


def _simulate(request: ExperimentRequest) -> ExperimentResponse:
    scenario = get_scenario(request.scenario_id)
    strategies = _strategies(request)
    runs: list[RunMetrics] = []
    for strategy in strategies:
        for offset in range(request.seeds):
            runs.append(
                run_simulation(
                    request.scenario_id,
                    strategy,
                    request.seed_start + offset,
                    failure_rate=request.failure_rate,
                    budget_cost=request.budget_cost,
                    budget_time=request.budget_time,
                    max_iterations=request.max_iterations,
                )
            )
    return ExperimentResponse(
        id=uuid4().hex[:12],
        status="completed",
        mode="sim",
        scenario_id=request.scenario_id,
        strategies=list(strategies),
        seeds=request.seeds,
        failure_rate=scenario.failure_rate if request.failure_rate is None else request.failure_rate,
        budget_cost=scenario.budget_cost if request.budget_cost is None else request.budget_cost,
        budget_time=scenario.budget_time if request.budget_time is None else request.budget_time,
        max_iterations=scenario.max_iterations if request.max_iterations is None else request.max_iterations,
        cost_label="Coordination cost",
        time_label="Simulated time",
        runs=runs,
        summaries=summarize(runs),
    )


async def _start_live(request: ExperimentRequest, scenario_failure: float) -> ExperimentResponse:
    if request.scenario_id != "easy":
        raise HTTPException(status_code=400, detail="Live mode runs the bundled easy task.")
    if request.strategy is None:
        raise HTTPException(status_code=400, detail="Live mode runs one strategy at a time.")
    if LIVE_LOCK.locked():
        raise HTTPException(status_code=409, detail="A live run is already in progress.")
    await LIVE_LOCK.acquire()
    experiment = ExperimentResponse(
        id=uuid4().hex[:12],
        status="running",
        mode="live",
        scenario_id="easy",
        strategies=[request.strategy],
        seeds=1,
        failure_rate=scenario_failure if request.failure_rate is None else request.failure_rate,
        budget_cost=request.budget_cost or get_scenario("easy").budget_cost,
        budget_time=request.budget_time or 720,
        max_iterations=request.max_iterations or 16,
        cost_label="Model runs",
        time_label="Wall time (seconds)",
        runs=[],
        summaries=[],
    )
    EXPERIMENTS[experiment.id] = experiment
    asyncio.get_running_loop().create_task(_live_task(experiment.id, request))
    return experiment


async def _live_task(experiment_id: str, request: ExperimentRequest) -> None:
    experiment = EXPERIMENTS[experiment_id]
    try:
        state = prepare_live_state(
            request.strategy or "sequential",
            request.seed_start,
            failure_rate=request.failure_rate,
            budget_cost=experiment.budget_cost,
            budget_time=experiment.budget_time,
            max_iterations=experiment.max_iterations,
        )
        experiment.runs = [
            RunMetrics(
                seed=state.seed,
                strategy=state.strategy,
                quality=0,
                cost=0,
                time=0,
                iterations=0,
                rework_cycles=0,
                model_runs=0,
                stopped_reason=None,
                events=state.events,
            )
        ]

        def on_event(event) -> None:
            _publish(experiment_id, {"type": "event", "event": event.model_dump()})

        metrics, model_id, workspace = await run_live(state, on_event)
        experiment.runs = [metrics]
        experiment.summaries = summarize([metrics])
        experiment.grok_model = model_id
        experiment.worktree = workspace
        experiment.status = "completed"
        _publish(experiment_id, {"type": "status", "status": "completed"})
    except Exception as exc:
        experiment.status = "error"
        experiment.error = str(exc)
        _publish(experiment_id, {"type": "status", "status": "error", "error": str(exc)})
    finally:
        if LIVE_LOCK.locked():
            LIVE_LOCK.release()


def _strategies(request: ExperimentRequest) -> tuple[Strategy, ...]:
    if request.strategy is None:
        return STRATEGIES
    return (request.strategy,)


def _scenario_or_404(scenario_id: str):
    try:
        return get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _publish(experiment_id: str, payload: dict) -> None:
    for queue in SUBSCRIBERS.get(experiment_id, []):
        queue.put_nowait(payload)
