from app.schemas import ModuleSpec, Scenario

SCENARIOS: dict[str, Scenario] = {
    "easy": Scenario(
        id="easy",
        name="Easy fan-out",
        summary="Two independent modules, then a report that depends on both. Little shared surface.",
        modules=[
            ModuleSpec(id="parser", complexity=0.3, dependencies=[], shared_surface="ingest"),
            ModuleSpec(id="rules", complexity=0.28, dependencies=[], shared_surface="policy"),
            ModuleSpec(id="report", complexity=0.34, dependencies=["parser", "rules"], shared_surface="output"),
        ],
        budget_cost=160,
        budget_time=220,
        max_iterations=40,
        failure_rate=0.05,
    ),
    "coupled": Scenario(
        id="coupled",
        name="Coupled surfaces",
        summary="Ingest and transform become ready together and share a surface. Parallel work can collide.",
        modules=[
            ModuleSpec(id="schema", complexity=0.42, dependencies=[], shared_surface="core"),
            ModuleSpec(id="ingest", complexity=0.55, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(id="transform", complexity=0.58, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(
                id="export",
                complexity=0.4,
                dependencies=["ingest", "transform"],
                shared_surface="pipeline",
            ),
        ],
        budget_cost=220,
        budget_time=280,
        max_iterations=48,
        failure_rate=0.08,
    ),
    "high_failure": Scenario(
        id="high_failure",
        name="High failure rate",
        summary="The coupled graph with agents that often error or drop handoffs.",
        modules=[
            ModuleSpec(id="schema", complexity=0.42, dependencies=[], shared_surface="core"),
            ModuleSpec(id="ingest", complexity=0.55, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(id="transform", complexity=0.58, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(
                id="export",
                complexity=0.4,
                dependencies=["ingest", "transform"],
                shared_surface="pipeline",
            ),
        ],
        budget_cost=320,
        budget_time=420,
        max_iterations=70,
        failure_rate=0.28,
    ),
    "tight_budget": Scenario(
        id="tight_budget",
        name="Tight budget",
        summary="The coupled graph with little cost, time, and iteration budget left.",
        modules=[
            ModuleSpec(id="schema", complexity=0.42, dependencies=[], shared_surface="core"),
            ModuleSpec(id="ingest", complexity=0.55, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(id="transform", complexity=0.58, dependencies=["schema"], shared_surface="pipeline"),
            ModuleSpec(
                id="export",
                complexity=0.4,
                dependencies=["ingest", "transform"],
                shared_surface="pipeline",
            ),
        ],
        budget_cost=48,
        budget_time=70,
        max_iterations=12,
        failure_rate=0.1,
    ),
}


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        known = ", ".join(SCENARIOS)
        raise KeyError(f"Unknown scenario '{scenario_id}'. Known scenarios: {known}") from exc


def list_scenarios() -> list[Scenario]:
    return list(SCENARIOS.values())
