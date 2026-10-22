from typing import Literal

from pydantic import BaseModel, Field


Role = Literal["architect", "developer", "tester", "reviewer"]
Strategy = Literal["sequential", "parallel", "supervisor"]
Mode = Literal["sim", "live"]
Outcome = Literal["success", "agent_error", "dropped", "rejected", "skipped", "conflict"]
StopReason = Literal["completed", "cost", "time", "iterations", "error"]


class ModuleSpec(BaseModel):
    id: str
    complexity: float = Field(ge=0, le=1)
    dependencies: list[str]
    shared_surface: str


class Scenario(BaseModel):
    id: str
    name: str
    summary: str
    modules: list[ModuleSpec]
    budget_cost: float
    budget_time: float
    max_iterations: int
    failure_rate: float


class ModuleState(BaseModel):
    id: str
    complexity: float
    dependencies: list[str]
    shared_surface: str
    latent_quality: float = 0.0
    defects: float = 1.0
    implemented: bool = False
    tested: bool = False
    test_passed: bool | None = None
    reviewed: bool = False
    review_passed: bool | None = None
    review_skipped: bool = False
    dev_attempts: int = 0
    abandoned: bool = False


class Assignment(BaseModel):
    role: Role
    module_id: str | None = None
    reason: str


class PlanStep(BaseModel):
    assignments: list[Assignment]
    skipped_reviews: list[str] = Field(default_factory=list)


class AssignmentEvent(BaseModel):
    superstep: int
    iteration: int
    role: Role
    module_id: str | None = None
    outcome: Outcome
    cost: float
    duration: float
    detail: str


class WorldState(BaseModel):
    scenario_id: str
    strategy: Strategy
    seed: int
    failure_rate: float
    budget_cost: float
    budget_time: float
    max_iterations: int
    has_spec: bool = False
    spec_quality: float = 0.0
    modules: dict[str, ModuleState]
    cost: float = 0.0
    time: float = 0.0
    iterations: int = 0
    rework_cycles: int = 0
    model_runs: int = 0
    last_failure: str | None = None
    stopped_reason: StopReason | None = None
    events: list[AssignmentEvent] = Field(default_factory=list)


class RunMetrics(BaseModel):
    seed: int
    strategy: Strategy
    quality: float
    cost: float
    time: float
    iterations: int
    rework_cycles: int
    model_runs: int
    stopped_reason: StopReason | None
    events: list[AssignmentEvent]


class StrategySummary(BaseModel):
    strategy: Strategy
    runs: int
    mean_quality: float
    mean_cost: float
    mean_time: float
    mean_iterations: float
    quality_ci_low: float
    quality_ci_high: float
    win_rate: float


class ExperimentRequest(BaseModel):
    strategy: Strategy | None = None
    scenario_id: str
    seeds: int = Field(default=30, ge=1, le=200)
    seed_start: int = Field(default=1, ge=0)
    budget_cost: float | None = Field(default=None, gt=0)
    budget_time: float | None = Field(default=None, gt=0)
    max_iterations: int | None = Field(default=None, ge=1, le=500)
    failure_rate: float | None = Field(default=None, ge=0, le=1)
    mode: Mode = "sim"


class ExperimentResponse(BaseModel):
    id: str
    status: Literal["running", "completed", "error"]
    mode: Mode
    scenario_id: str
    strategies: list[Strategy]
    seeds: int
    failure_rate: float
    budget_cost: float
    budget_time: float
    max_iterations: int
    cost_label: str
    time_label: str
    runs: list[RunMetrics]
    summaries: list[StrategySummary]
    error: str | None = None
    grok_model: str | None = None
    worktree: str | None = None


class HealthResponse(BaseModel):
    grok_api_key_configured: bool
    live_busy: bool
