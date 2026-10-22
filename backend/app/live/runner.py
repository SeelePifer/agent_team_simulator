import asyncio
import json
import random
import re
import sys
import time
from dataclasses import dataclass

from app.coordination.policies import plan_step
from app.coordination.rules import budget_stop, failure_key, role_cost
from app.live.grok import GrokError, GrokSession, grok_api_key, resolve_model
from app.live.worktree import create_workspace, task_dir
from app.schemas import Assignment, AssignmentEvent, RunMetrics, Strategy, WorldState
from app.simulation.engine import initial_state, run_quality
from app.simulation.scenarios import get_scenario

LIVE_WALL_CAP_SECONDS = 15 * 60
LIVE_MODEL_CAP = 12

TEST_KEYWORDS = {
    "parser": "mean",
    "rules": "normalize",
    "report": "report",
}


@dataclass
class Attempt:
    outcome: str
    duration: float
    detail: str
    used_model: bool
    rubric: float | None = None


def prepare_live_state(
    strategy: Strategy,
    seed: int,
    *,
    failure_rate: float | None,
    budget_cost: float | None,
    budget_time: float | None,
    max_iterations: int | None,
) -> WorldState:
    scenario = get_scenario("easy")
    return initial_state(
        scenario,
        strategy,
        seed,
        failure_rate=0.0 if failure_rate is None else failure_rate,
        budget_cost=budget_cost,
        budget_time=budget_time,
        max_iterations=max_iterations,
    )


async def run_live(state: WorldState, on_event) -> tuple[RunMetrics, str, str]:
    api_key = grok_api_key()
    workspace = create_workspace(f"{state.strategy}-{state.seed}-{int(time.time())}")
    directory = task_dir(workspace)
    if not (directory / "test_stats.py").exists():
        raise RuntimeError(f"Sample task is missing at {directory}")
    model_id = await asyncio.to_thread(resolve_model, api_key)
    agents = {
        role: GrokSession(role=role, model=model_id, directory=directory, allow_write=role != "reviewer")
        for role in ("architect", "developer", "reviewer")
    }
    started = time.monotonic()
    await _orchestrate(state, agents, directory, started, on_event)
    if state.stopped_reason is None:
        state.stopped_reason = "iterations"
    return _metrics(state), model_id, str(workspace)


async def _orchestrate(state, agents, directory, started: float, on_event) -> None:
    rng = random.Random(state.seed)
    superstep = 0
    while superstep < 500:
        if time.monotonic() - started >= LIVE_WALL_CAP_SECONDS or state.model_runs >= LIVE_MODEL_CAP:
            state.stopped_reason = "time" if state.model_runs < LIVE_MODEL_CAP else "iterations"
            return
        stop = budget_stop(state)
        if stop:
            state.stopped_reason = stop
            return
        step = plan_step(state.strategy, state)
        for module_id in step.skipped_reviews:
            _append(state, superstep, "reviewer", module_id, "skipped", 0, 0, f"Supervisor accepted {module_id} without review")
            on_event(state.events[-1])
        if not step.assignments:
            state.stopped_reason = "completed"
            return
        batch = _assignments_within_budget(state, step.assignments)
        if not batch:
            return
        attempts = await _dispatch(state, batch, agents, directory, rng)
        _commit(state, batch, attempts, superstep, on_event)
        superstep += 1


async def _dispatch(state, batch, agents, directory, rng: random.Random) -> list[Attempt]:
    planned = [_inject(state, assignment, rng) for assignment in batch]
    pending = [index for index, attempt in enumerate(planned) if attempt is None]
    if state.strategy == "parallel" and len(pending) > 1:
        ran = await asyncio.gather(*[_execute(batch[index], agents, directory) for index in pending])
        for index, attempt in zip(pending, ran, strict=True):
            planned[index] = attempt
        return [attempt for attempt in planned if attempt is not None]
    for index in pending:
        planned[index] = await _execute(batch[index], agents, directory)
    return [attempt for attempt in planned if attempt is not None]


def _inject(state: WorldState, assignment: Assignment, rng: random.Random) -> Attempt | None:
    multiplier = 1.15 if assignment.role == "developer" else 1.0
    if rng.random() < min(0.95, state.failure_rate * multiplier):
        return Attempt("agent_error", 0.0, f"Injected agent error on {assignment.role}", False)
    if rng.random() < state.failure_rate * 0.35:
        return Attempt("dropped", 0.0, f"Injected dropped handoff for {assignment.role}", False)
    return None


async def _execute(assignment: Assignment, agents: dict[str, GrokSession], directory) -> Attempt:
    started = time.monotonic()
    if assignment.role == "tester":
        passed, failed, output = await _pytest(directory, assignment.module_id or "")
        duration = time.monotonic() - started
        if passed + failed == 0:
            return Attempt("agent_error", duration, f"pytest produced no tests. {output[-400:]}", False)
        rate = passed / (passed + failed)
        outcome = "success" if failed == 0 else "rejected"
        return Attempt(outcome, duration, f"pytest {assignment.module_id}: {passed} passed, {failed} failed", False, rate)
    prompt = _prompt(assignment)
    if assignment.role == "reviewer":
        prompt = f"{prompt}\n\nCurrent files:\n{_snapshot(directory)}"
    try:
        text = await asyncio.to_thread(agents[assignment.role].complete, prompt)
    except GrokError as exc:
        return Attempt("agent_error", time.monotonic() - started, str(exc), True)
    duration = time.monotonic() - started
    if assignment.role == "architect" and not (directory / "DESIGN.md").exists():
        return Attempt("agent_error", duration, "Architect finished without writing DESIGN.md", True)
    if assignment.role == "reviewer":
        rubric = _parse_rubric(text)
        if rubric is None:
            return Attempt("agent_error", duration, "Reviewer did not return JSON", True)
        outcome = "success" if rubric["passed"] else "rejected"
        return Attempt(outcome, duration, str(rubric["notes"]), True, float(rubric["score"]))
    target = assignment.module_id or "the spec"
    return Attempt("success", duration, f"{assignment.role} finished {target}", True)


def _commit(state: WorldState, batch: list[Assignment], attempts: list[Attempt], superstep: int, on_event) -> None:
    module_count = len(state.modules)
    for assignment, attempt in zip(batch, attempts, strict=True):
        complexity = 0.4 if assignment.module_id is None else state.modules[assignment.module_id].complexity
        full_cost = role_cost(assignment.role, complexity, module_count)
        paid = full_cost * 0.5 if attempt.outcome == "dropped" else full_cost
        state.cost += paid
        state.iterations += 1
        if attempt.used_model:
            state.model_runs += 1
        if attempt.outcome in {"agent_error", "dropped"}:
            state.last_failure = failure_key(assignment.role, assignment.module_id)
            if assignment.role == "developer" and assignment.module_id and attempt.outcome == "agent_error":
                state.modules[assignment.module_id].dev_attempts += 1
        else:
            state.last_failure = None
            _apply_success(state, assignment, attempt)
        _append(state, superstep, assignment.role, assignment.module_id, attempt.outcome, paid, attempt.duration, attempt.detail)
        on_event(state.events[-1])
    state.time += max(attempt.duration for attempt in attempts) if attempts else 0.0


def _apply_success(state: WorldState, assignment: Assignment, attempt: Attempt) -> None:
    if assignment.role == "architect":
        state.has_spec = True
        state.spec_quality = 0.8
        return
    module = state.modules[assignment.module_id or ""]
    if assignment.role == "developer":
        if module.implemented:
            state.rework_cycles += 1
        module.dev_attempts += 1
        module.implemented = True
        module.tested = False
        module.test_passed = None
        module.reviewed = False
        module.review_passed = None
        module.review_skipped = False
        module.latent_quality = 0.55
        module.defects = 0.35
        return
    if assignment.role == "tester":
        rate = attempt.rubric or 0.0
        module.tested = True
        module.test_passed = attempt.outcome == "success"
        module.latent_quality = 0.2 + 0.75 * rate
        module.defects = 0.05 + 0.7 * (1 - rate)
        return
    score = attempt.rubric or 0.0
    module.reviewed = True
    module.review_passed = attempt.outcome == "success" and score >= 0.6
    module.latent_quality = min(1.0, module.latent_quality * 0.75 + score * 0.25)


def _assignments_within_budget(state: WorldState, assignments: list[Assignment]) -> list[Assignment]:
    module_count = len(state.modules)
    fitted: list[Assignment] = []
    cost = state.cost
    for assignment in assignments:
        complexity = 0.4 if assignment.module_id is None else state.modules[assignment.module_id].complexity
        cost += role_cost(assignment.role, complexity, module_count)
        if cost > state.budget_cost:
            state.stopped_reason = "cost"
            break
        if state.iterations + len(fitted) + 1 > state.max_iterations:
            state.stopped_reason = "iterations"
            break
        fitted.append(assignment)
    if fitted:
        state.stopped_reason = None
    return fitted


def _append(state, superstep, role, module_id, outcome, cost, duration, detail) -> None:
    state.events.append(
        AssignmentEvent(
            superstep=superstep,
            iteration=state.iterations,
            role=role,
            module_id=module_id,
            outcome=outcome,
            cost=round(cost, 3),
            duration=round(duration, 3),
            detail=detail,
        )
    )


def _metrics(state: WorldState) -> RunMetrics:
    return RunMetrics(
        seed=state.seed,
        strategy=state.strategy,
        quality=round(run_quality(state), 4),
        cost=float(state.model_runs),
        time=round(state.time, 3),
        iterations=state.iterations,
        rework_cycles=state.rework_cycles,
        model_runs=state.model_runs,
        stopped_reason=state.stopped_reason,
        events=state.events,
    )


async def _pytest(directory, module_id: str) -> tuple[int, int, str]:
    keyword = TEST_KEYWORDS.get(module_id, module_id)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=line",
        "-k",
        keyword,
        cwd=str(directory),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    raw, _ = await process.communicate()
    text = raw.decode("utf-8", errors="replace")
    passed = int(match.group(1)) if (match := re.search(r"(\d+) passed", text)) else 0
    failed = int(match.group(1)) if (match := re.search(r"(\d+) failed", text)) else 0
    errors = int(match.group(1)) if (match := re.search(r"(\d+) error", text)) else 0
    return passed, failed + errors, text


def _snapshot(directory) -> str:
    chunks: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in {".py", ".md"}:
            continue
        chunks.append(f"--- {path.name} ---\n{path.read_text(encoding='utf-8')[:8000]}")
    return "\n".join(chunks)


def _prompt(assignment: Assignment) -> str:
    if assignment.role == "architect":
        return (
            "You are the architect. Read mean.py, normalize.py, report.py, and test_stats.py. "
            "Write DESIGN.md with the contract for mean, normalize_scores, and build_report, "
            "including edge cases and which file owns each function. Do not modify tests or implementations."
        )
    if assignment.role == "developer":
        return (
            f"You are the developer assigned to module '{assignment.module_id}'. "
            "parser is mean() in mean.py. rules is normalize_scores() in normalize.py. "
            "report is build_report() in report.py and may call the other two. "
            "Implement only that module so its tests pass. Follow DESIGN.md if present. "
            "Do not edit test_stats.py."
        )
    return (
        "You are the reviewer. Read the implementation and DESIGN.md. "
        'Reply with only JSON, no markdown: {"score": <float 0 to 1>, '
        '"passed": <true if edge cases are handled>, "notes": "<one sentence>"}'
    )


def _parse_rubric(text: str) -> dict[str, float | bool | str] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if "score" not in payload or "passed" not in payload:
        return None
    return {
        "score": float(payload["score"]),
        "passed": bool(payload["passed"]),
        "notes": str(payload.get("notes", "Review recorded")),
    }
