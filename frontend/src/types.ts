export type Strategy = 'sequential' | 'parallel' | 'supervisor'
export type Mode = 'sim' | 'live'

export interface Scenario {
  id: string
  name: string
  summary: string
  budget_cost: number
  budget_time: number
  max_iterations: number
  failure_rate: number
}

export interface AssignmentEvent {
  superstep: number
  iteration: number
  role: string
  module_id: string | null
  outcome: string
  cost: number
  duration: number
  detail: string
}

export interface RunMetrics {
  seed: number
  strategy: Strategy
  quality: number
  cost: number
  time: number
  iterations: number
  rework_cycles: number
  model_runs: number
  stopped_reason: string | null
  events: AssignmentEvent[]
}

export interface StrategySummary {
  strategy: Strategy
  runs: number
  mean_quality: number
  mean_cost: number
  mean_time: number
  mean_iterations: number
  quality_ci_low: number
  quality_ci_high: number
  win_rate: number
}

export interface Experiment {
  id: string
  status: 'running' | 'completed' | 'error'
  mode: Mode
  scenario_id: string
  strategies: Strategy[]
  seeds: number
  failure_rate: number
  budget_cost: number
  budget_time: number
  max_iterations: number
  cost_label: string
  time_label: string
  runs: RunMetrics[]
  summaries: StrategySummary[]
  error: string | null
  grok_model: string | null
  worktree: string | null
}

export interface Health {
  grok_api_key_configured: boolean
  live_busy: boolean
}

export interface ExperimentInput {
  strategy: Strategy | null
  scenario_id: string
  seeds: number
  seed_start: number
  budget_cost: number
  budget_time: number
  max_iterations: number
  failure_rate: number
  mode: Mode
}
