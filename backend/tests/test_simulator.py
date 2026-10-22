from collections import Counter

from fastapi.testclient import TestClient

from app.main import app
from app.simulation.engine import run_simulation
from app.simulation.metrics import summarize


def test_same_seed_is_reproducible() -> None:
    first = run_simulation("coupled", "supervisor", 11, failure_rate=0.15)
    second = run_simulation("coupled", "supervisor", 11, failure_rate=0.15)
    assert first.model_dump() == second.model_dump()


def test_parallel_is_faster_on_independent_work() -> None:
    parallel = run_simulation("easy", "parallel", 7, failure_rate=0)
    sequential = run_simulation("easy", "sequential", 7, failure_rate=0)
    assert parallel.stopped_reason == "completed"
    assert sequential.stopped_reason == "completed"
    assert parallel.quality > 0.45
    assert sequential.quality > 0.45
    assert parallel.time < sequential.time


def test_parallel_conflicts_and_sequential_does_not() -> None:
    parallel = run_simulation("coupled", "parallel", 3, failure_rate=0)
    sequential = run_simulation("coupled", "sequential", 3, failure_rate=0)
    assert any("Integration conflict" in event.detail for event in parallel.events)
    assert all("Integration conflict" not in event.detail for event in sequential.events)
    per_step: Counter[int] = Counter()
    for event in sequential.events:
        per_step[event.superstep] += 1
    assert all(count == 1 for count in per_step.values())
    developers: Counter[int] = Counter()
    for event in parallel.events:
        if event.role == "developer" and event.outcome == "success":
            developers[event.superstep] += 1
    assert max(developers.values()) >= 2


def test_tight_budget_stops_early() -> None:
    run = run_simulation("tight_budget", "sequential", 1)
    assert run.stopped_reason in {"cost", "time", "iterations"}
    assert run.cost <= 48.05


def test_win_rates_sum_to_one() -> None:
    runs = []
    for strategy in ("sequential", "parallel", "supervisor"):
        for seed in range(1, 9):
            runs.append(run_simulation("high_failure", strategy, seed))
    summaries = summarize(runs)
    assert abs(sum(item.win_rate for item in summaries) - 1) < 1e-6


def test_api_compare_returns_four_metrics() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/experiments",
        json={"scenario_id": "easy", "seeds": 4, "failure_rate": 0, "mode": "sim"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["summaries"]) == 3
    for summary in body["summaries"]:
        for key in ("mean_quality", "mean_cost", "mean_time", "mean_iterations"):
            assert key in summary
    fetched = client.get(f"/api/experiments/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["runs"][0]["events"]


def test_live_requires_one_strategy_and_the_bundled_task() -> None:
    client = TestClient(app)
    missing = client.post("/api/experiments", json={"scenario_id": "easy", "mode": "live"})
    assert missing.status_code == 400
    coupled = client.post(
        "/api/experiments",
        json={"scenario_id": "coupled", "strategy": "sequential", "mode": "live"},
    )
    assert coupled.status_code == 400
