import math
import statistics

from app.schemas import RunMetrics, Strategy, StrategySummary


def summarize(runs: list[RunMetrics]) -> list[StrategySummary]:
    if not runs:
        return []
    strategies: list[Strategy] = []
    for run in runs:
        if run.strategy not in strategies:
            strategies.append(run.strategy)
    wins = {strategy: 0.0 for strategy in strategies}
    by_seed: dict[int, list[RunMetrics]] = {}
    for run in runs:
        by_seed.setdefault(run.seed, []).append(run)
    for group in by_seed.values():
        best_quality = max(item.quality for item in group)
        contenders = [item for item in group if math.isclose(item.quality, best_quality, abs_tol=1e-9)]
        best_cost = min(item.cost for item in contenders)
        contenders = [item for item in contenders if math.isclose(item.cost, best_cost, abs_tol=1e-6)]
        share = 1 / len(contenders)
        for item in contenders:
            wins[item.strategy] += share
    seed_count = len(by_seed)
    summaries: list[StrategySummary] = []
    for strategy in strategies:
        grouped = [run for run in runs if run.strategy == strategy]
        qualities = [run.quality for run in grouped]
        low, high = _ci95(qualities)
        summaries.append(
            StrategySummary(
                strategy=strategy,
                runs=len(grouped),
                mean_quality=round(_mean(qualities), 4),
                mean_cost=round(_mean([run.cost for run in grouped]), 3),
                mean_time=round(_mean([run.time for run in grouped]), 3),
                mean_iterations=round(_mean([float(run.iterations) for run in grouped]), 3),
                quality_ci_low=round(low, 4),
                quality_ci_high=round(high, 4),
                win_rate=round(wins[strategy] / seed_count, 4),
            )
        )
    return summaries


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _ci95(values: list[float]) -> tuple[float, float]:
    center = _mean(values)
    if len(values) < 2:
        return center, center
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return center - half, center + half
