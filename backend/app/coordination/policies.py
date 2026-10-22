from app.coordination.rules import (
    dependency_ready,
    failure_key,
    is_closed,
    mark_abandoned,
    needs_developer,
    role_cost,
)
from app.schemas import Assignment, PlanStep, Strategy, WorldState


def plan_step(strategy: Strategy, state: WorldState) -> PlanStep:
    mark_abandoned(state)
    if strategy == "sequential":
        return PlanStep(assignments=_sequential(state))
    if strategy == "parallel":
        return PlanStep(assignments=_parallel(state))
    skipped = _settle_supervisor(state)
    return PlanStep(assignments=_supervisor(state), skipped_reviews=skipped)


def _sequential(state: WorldState) -> list[Assignment]:
    if not state.has_spec:
        return [
            Assignment(
                role="architect",
                reason="Sequential pipeline starts with a single architecture pass",
            )
        ]
    for module in state.modules.values():
        if is_closed(module) or not dependency_ready(state, module):
            continue
        if needs_developer(module):
            return [
                Assignment(
                    role="developer",
                    module_id=module.id,
                    reason=f"Sequential pipeline implements {module.id} before the next module",
                )
            ]
        if not module.tested:
            return [
                Assignment(
                    role="tester",
                    module_id=module.id,
                    reason=f"Sequential pipeline tests {module.id} before review",
                )
            ]
        if module.test_passed and not module.reviewed:
            return [
                Assignment(
                    role="reviewer",
                    module_id=module.id,
                    reason=f"Sequential pipeline reviews {module.id} before moving on",
                )
            ]
    return []


def _parallel(state: WorldState) -> list[Assignment]:
    if not state.has_spec:
        return [
            Assignment(
                role="architect",
                reason="Parallel team waits for one architecture pass, then fans out",
            )
        ]
    developers = [
        Assignment(
            role="developer",
            module_id=module.id,
            reason=f"Ready module {module.id} joins this development superstep",
        )
        for module in state.modules.values()
        if dependency_ready(state, module) and needs_developer(module)
    ]
    if developers:
        return developers
    testers = [
        Assignment(
            role="tester",
            module_id=module.id,
            reason=f"Barrier reached; test {module.id} before the next wave",
        )
        for module in state.modules.values()
        if module.implemented and not module.tested and not module.abandoned
    ]
    if testers:
        return testers
    reviewers = [
        Assignment(
            role="reviewer",
            module_id=module.id,
            reason=f"Integration barrier; review {module.id}",
        )
        for module in state.modules.values()
        if module.test_passed and not module.reviewed and not module.abandoned
    ]
    return reviewers


def _settle_supervisor(state: WorldState) -> list[str]:
    if not state.has_spec or state.budget_cost <= 0 or state.budget_time <= 0:
        return []
    remaining_cost = (state.budget_cost - state.cost) / state.budget_cost
    remaining_time = (state.budget_time - state.time) / state.budget_time
    comfortable = min(remaining_cost, remaining_time) > 0.22
    skipped: list[str] = []
    for module in state.modules.values():
        if not (module.implemented and module.tested and module.test_passed and not module.reviewed):
            continue
        uncertain = module.latent_quality < 0.75 or module.defects > 0.18
        if comfortable and uncertain:
            continue
        module.review_skipped = True
        module.reviewed = True
        skipped.append(module.id)
    return skipped


def _supervisor(state: WorldState) -> list[Assignment]:
    best_score = -1.0
    best: Assignment | None = None
    module_count = len(state.modules)

    def consider(score: float, assignment: Assignment) -> None:
        nonlocal best_score, best
        if score > best_score:
            best_score = score
            best = assignment

    if not state.has_spec:
        consider(
            1_000,
            Assignment(
                role="architect",
                reason="Supervisor has no spec, so the architect goes first",
            ),
        )
        return [best] if best else []

    for module in state.modules.values():
        if module.abandoned or not dependency_ready(state, module):
            continue
        if needs_developer(module):
            dependents = sum(
                1
                for other in state.modules.values()
                if module.id in other.dependencies and not other.implemented
            )
            score = (1 + dependents) * (0.5 + module.complexity) / role_cost(
                "developer", module.complexity, module_count
            )
            if module.test_passed is False:
                score += 0.35
            if state.last_failure == failure_key("developer", module.id):
                score -= 0.2
            reason = f"Supervisor assigns development of {module.id}"
            if module.test_passed is False or module.review_passed is False:
                reason = f"Supervisor sends {module.id} back for rework"
            consider(
                score,
                Assignment(role="developer", module_id=module.id, reason=reason),
            )
            continue
        if module.implemented and not module.tested:
            score = (0.45 + module.defects) / role_cost("tester", module.complexity, module_count)
            if state.last_failure == failure_key("tester", module.id):
                score -= 0.2
            consider(
                score,
                Assignment(
                    role="tester",
                    module_id=module.id,
                    reason=f"Supervisor tests {module.id} before spending more implementation",
                ),
            )
            continue
        if module.test_passed and not module.reviewed and not module.review_skipped:
            score = (1.1 - module.latent_quality) / role_cost(
                "reviewer", module.complexity, module_count
            )
            if state.last_failure == failure_key("reviewer", module.id):
                score -= 0.2
            consider(
                score,
                Assignment(
                    role="reviewer",
                    module_id=module.id,
                    reason=f"Quality of {module.id} is still uncertain and budget remains",
                ),
            )
    return [best] if best else []
