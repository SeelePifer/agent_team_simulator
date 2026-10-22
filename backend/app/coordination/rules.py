from typing import Literal

from app.schemas import ModuleState, Role, WorldState

MAX_DEV_ATTEMPTS = 3


def role_cost(role: Role, complexity: float, module_count: int) -> float:
    if role == "architect":
        return 6 + 2 * module_count
    if role == "developer":
        return 4 + 9 * complexity
    if role == "tester":
        return 2.5 + 3 * complexity
    return 2 + 2.5 * complexity


def role_time(role: Role, complexity: float, module_count: int) -> float:
    if role == "architect":
        return 8 + 1.5 * module_count
    if role == "developer":
        return 7 + 10 * complexity
    if role == "tester":
        return 4 + 4 * complexity
    return 3.5 + 3 * complexity


def dependency_ready(state: WorldState, module: ModuleState) -> bool:
    for dep_id in module.dependencies:
        dep = state.modules[dep_id]
        if dep.implemented or dep.abandoned:
            continue
        return False
    return True


def needs_developer(module: ModuleState) -> bool:
    if module.abandoned or module.dev_attempts >= MAX_DEV_ATTEMPTS:
        return False
    if not module.implemented:
        return True
    if module.tested and module.test_passed is False:
        return True
    if module.reviewed and module.review_passed is False and not module.review_skipped:
        return True
    return False


def is_closed(module: ModuleState) -> bool:
    if module.abandoned:
        return True
    if not (module.implemented and module.tested and module.test_passed):
        return False
    if module.review_skipped:
        return True
    return bool(module.reviewed and module.review_passed)


def mark_abandoned(state: WorldState) -> None:
    for module in state.modules.values():
        if module.abandoned or module.dev_attempts < MAX_DEV_ATTEMPTS:
            continue
        if not module.implemented or (module.tested and module.test_passed is False):
            module.abandoned = True
            continue
        if module.reviewed and module.review_passed is False:
            module.abandoned = True


def budget_stop(state: WorldState) -> Literal["cost", "time", "iterations"] | None:
    if state.iterations >= state.max_iterations:
        return "iterations"
    if state.cost >= state.budget_cost:
        return "cost"
    if state.time >= state.budget_time:
        return "time"
    return None


def failure_key(role: Role, module_id: str | None) -> str:
    return f"{role}:{module_id or '*'}"
