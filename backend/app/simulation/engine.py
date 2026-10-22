import random

from app.coordination.policies import plan_step
from app.coordination.rules import budget_stop, failure_key, role_cost, role_time
from app.schemas import Assignment, AssignmentEvent, ModuleState, RunMetrics, Scenario, Strategy, WorldState
from app.simulation.scenarios import get_scenario


def module_quality(module: ModuleState) -> float:
    if not module.implemented:
        return 0.0
    score = module.latent_quality * (1 - 0.45 * module.defects)
    if module.tested and module.test_passed:
        score *= 1.0
    elif module.tested and module.test_passed is False:
        score *= 0.72
    else:
        score *= 0.8
    if module.review_skipped:
        score *= 0.94
    elif module.reviewed and module.review_passed:
        score *= 1.0
    elif module.reviewed and module.review_passed is False:
        score *= 0.88
    else:
        score *= 0.9
    return max(0.0, min(1.0, score))


def run_quality(state: WorldState) -> float:
    if not state.modules:
        return 0.0
    total = sum(module_quality(module) for module in state.modules.values())
    return total / len(state.modules)


def initial_state(
    scenario: Scenario,
    strategy: Strategy,
    seed: int,
    *,
    failure_rate: float | None = None,
    budget_cost: float | None = None,
    budget_time: float | None = None,
    max_iterations: int | None = None,
) -> WorldState:
    modules = {
        spec.id: ModuleState(
            id=spec.id,
            complexity=spec.complexity,
            dependencies=list(spec.dependencies),
            shared_surface=spec.shared_surface,
        )
        for spec in scenario.modules
    }
    return WorldState(
        scenario_id=scenario.id,
        strategy=strategy,
        seed=seed,
        failure_rate=scenario.failure_rate if failure_rate is None else failure_rate,
        budget_cost=scenario.budget_cost if budget_cost is None else budget_cost,
        budget_time=scenario.budget_time if budget_time is None else budget_time,
        max_iterations=scenario.max_iterations if max_iterations is None else max_iterations,
        modules=modules,
    )


def run_simulation(
    scenario_id: str,
    strategy: Strategy,
    seed: int,
    *,
    failure_rate: float | None = None,
    budget_cost: float | None = None,
    budget_time: float | None = None,
    max_iterations: int | None = None,
) -> RunMetrics:
    scenario = get_scenario(scenario_id)
    state = initial_state(
        scenario,
        strategy,
        seed,
        failure_rate=failure_rate,
        budget_cost=budget_cost,
        budget_time=budget_time,
        max_iterations=max_iterations,
    )
    rng = random.Random(seed)
    superstep = 0
    while superstep < 500:
        stop = budget_stop(state)
        if stop:
            state.stopped_reason = stop
            break
        step = plan_step(strategy, state)
        for module_id in step.skipped_reviews:
            _record(
                state,
                superstep,
                Assignment(role="reviewer", module_id=module_id, reason=""),
                "skipped",
                0,
                0,
                f"Supervisor accepted {module_id} without review",
            )
        if not step.assignments:
            state.stopped_reason = "completed"
            break
        batch = _fit_budget(state, step.assignments)
        if not batch:
            break
        _apply_superstep(state, strategy, batch, rng, superstep)
        superstep += 1
    if state.stopped_reason is None:
        state.stopped_reason = "iterations"
    return _metrics(state)


def _fit_budget(state: WorldState, assignments: list[Assignment]) -> list[Assignment]:
    module_count = len(state.modules)
    fitted: list[Assignment] = []
    cost = state.cost
    longest = 0.0
    for assignment in assignments:
        complexity = _complexity(state, assignment)
        next_cost = cost + role_cost(assignment.role, complexity, module_count)
        duration = role_time(assignment.role, complexity, module_count)
        if next_cost > state.budget_cost:
            state.stopped_reason = "cost"
            break
        if state.iterations + len(fitted) + 1 > state.max_iterations:
            state.stopped_reason = "iterations"
            break
        projected = max(longest, duration)
        if state.time + projected > state.budget_time:
            state.stopped_reason = "time"
            break
        fitted.append(assignment)
        cost = next_cost
        longest = projected
    if fitted:
        state.stopped_reason = None
    return fitted


def _apply_superstep(
    state: WorldState,
    strategy: Strategy,
    assignments: list[Assignment],
    rng: random.Random,
    superstep: int,
) -> None:
    durations: list[float] = []
    developed: list[str] = []
    for assignment in assignments:
        duration, developed_id = _apply_one(state, assignment, rng, superstep)
        durations.append(duration)
        if developed_id:
            developed.append(developed_id)
    if strategy == "parallel":
        _apply_conflicts(state, developed, superstep)
    state.time += max(durations) if durations else 0.0


def _apply_one(
    state: WorldState,
    assignment: Assignment,
    rng: random.Random,
    superstep: int,
) -> tuple[float, str | None]:
    module = state.modules[assignment.module_id] if assignment.module_id else None
    complexity = module.complexity if module else 0.4
    module_count = len(state.modules)
    cost = role_cost(assignment.role, complexity, module_count)
    duration = role_time(assignment.role, complexity, module_count)
    state.cost += cost
    state.iterations += 1
    if _agent_failed(state, assignment.role, complexity, rng):
        state.last_failure = failure_key(assignment.role, assignment.module_id)
        if module and assignment.role == "developer":
            module.dev_attempts += 1
        _record(state, superstep, assignment, "agent_error", cost, duration, _failure_detail(assignment, "errored"))
        return duration, None
    if rng.random() < state.failure_rate * 0.35:
        state.last_failure = failure_key(assignment.role, assignment.module_id)
        _record(state, superstep, assignment, "dropped", cost * 0.5, duration * 0.5, _failure_detail(assignment, "dropped the handoff"))
        state.cost -= cost * 0.5
        return duration * 0.5, None
    state.last_failure = None
    developed_id = _apply_success(state, assignment, rng)
    outcome: Outcome = "success"
    detail = _success_detail(assignment)
    if assignment.role in {"tester", "reviewer"} and module is not None:
        passed = module.test_passed if assignment.role == "tester" else module.review_passed
        if passed is False:
            outcome = "rejected"
            detail = f"{assignment.role} rejected {module.id}"
    _record(state, superstep, assignment, outcome, cost, duration, detail)
    return duration, developed_id


def _apply_success(state: WorldState, assignment: Assignment, rng: random.Random) -> str | None:
    if assignment.role == "architect":
        state.has_spec = True
        state.spec_quality = min(1.0, 0.68 + 0.28 * rng.random())
        return None
    module = state.modules[assignment.module_id or ""]
    if assignment.role == "developer":
        rework = module.implemented
        if rework:
            state.rework_cycles += 1
        module.dev_attempts += 1
        latent, defects = _draw_quality(state, module, rng, rework)
        module.latent_quality = latent
        module.defects = defects
        module.implemented = True
        module.tested = False
        module.test_passed = None
        module.reviewed = False
        module.review_passed = None
        module.review_skipped = False
        return module.id
    if assignment.role == "tester":
        module.tested = True
        module.test_passed = module.defects < 0.42
        if module.test_passed:
            module.defects *= 0.55
        return None
    module.reviewed = True
    module.review_passed = module.latent_quality >= 0.2 and module.defects <= 0.5
    if module.review_passed:
        module.defects *= 0.8
    return None


def _draw_quality(
    state: WorldState,
    module: ModuleState,
    rng: random.Random,
    rework: bool,
) -> tuple[float, float]:
    skill = rng.betavariate(2.4, 1.3)
    spec = state.spec_quality if state.has_spec else 0.35
    dep_factor = _dependency_factor(state, module)
    draw = (0.28 + 0.5 * skill) * (1 - 0.28 * module.complexity) * dep_factor + 0.2 * spec
    draw = min(1.0, max(0.08, draw))
    latent = min(1.0, module.latent_quality * 0.35 + draw * 0.8) if rework else draw
    defects = (1 - latent) * (0.32 + 0.4 * module.complexity)
    return latent, defects


def _dependency_factor(state: WorldState, module: ModuleState) -> float:
    if not module.dependencies:
        return 1.0
    scores: list[float] = []
    for dep_id in module.dependencies:
        dep = state.modules[dep_id]
        if dep.implemented:
            scores.append(0.6 + 0.4 * dep.latent_quality)
            continue
        scores.append(0.4)
    return sum(scores) / len(scores)


def _apply_conflicts(state: WorldState, developed: list[str], superstep: int) -> None:
    grouped: dict[str, list[str]] = {}
    for module_id in developed:
        surface = state.modules[module_id].shared_surface
        grouped.setdefault(surface, []).append(module_id)
    for module_ids in grouped.values():
        if len(module_ids) < 2:
            continue
        names = ", ".join(module_ids)
        for module_id in module_ids:
            module = state.modules[module_id]
            module.latent_quality = max(0.0, module.latent_quality * 0.75)
            module.defects = min(1.0, module.defects + 0.2)
            _record(
                state,
                superstep,
                Assignment(role="developer", module_id=module_id, reason=""),
                "conflict",
                0,
                0,
                f"Integration conflict on shared surface between {names}",
            )


def _agent_failed(state: WorldState, role: str, complexity: float, rng: random.Random) -> bool:
    multiplier = 1.15 if role == "developer" else 1.0
    probability = state.failure_rate * multiplier * (1 + 0.35 * complexity)
    return rng.random() < min(0.95, probability)


def _complexity(state: WorldState, assignment: Assignment) -> float:
    if assignment.module_id is None:
        return 0.4
    return state.modules[assignment.module_id].complexity


def _record(
    state: WorldState,
    superstep: int,
    assignment: Assignment,
    outcome: str,
    cost: float,
    duration: float,
    detail: str,
) -> None:
    state.events.append(
        AssignmentEvent(
            superstep=superstep,
            iteration=state.iterations,
            role=assignment.role,
            module_id=assignment.module_id,
            outcome=outcome,  # type: ignore[arg-type]
            cost=round(cost, 3),
            duration=round(duration, 3),
            detail=detail,
        )
    )


def _success_detail(assignment: Assignment) -> str:
    if assignment.role == "architect":
        return "Architect published the spec"
    return f"{assignment.role} finished {assignment.module_id}"


def _failure_detail(assignment: Assignment, verb: str) -> str:
    target = assignment.module_id or "the run"
    return f"{assignment.role} {verb} on {target}"


def _metrics(state: WorldState) -> RunMetrics:
    return RunMetrics(
        seed=state.seed,
        strategy=state.strategy,
        quality=round(run_quality(state), 4),
        cost=round(state.cost, 3),
        time=round(state.time, 3),
        iterations=state.iterations,
        rework_cycles=state.rework_cycles,
        model_runs=state.model_runs,
        stopped_reason=state.stopped_reason,
        events=state.events,
    )
