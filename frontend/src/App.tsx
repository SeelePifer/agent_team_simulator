import { useEffect, useMemo, useState } from 'react'
import { createExperiment, fetchExperiment, fetchHealth, fetchScenarios } from './api'
import type { Experiment, Health, Mode, Scenario, Strategy, StrategySummary } from './types'

const STRATEGIES: { id: Strategy | ''; label: string; copy: string }[] = [
  { id: '', label: 'Compare all', copy: 'Run sequential, parallel, and supervisor on the same seeds.' },
  { id: 'sequential', label: 'Sequential', copy: 'Architect, developer, tester, reviewer, one module at a time.' },
  { id: 'parallel', label: 'Parallel', copy: 'Ready modules fan out together and wait at a barrier. Shared surfaces can conflict.' },
  { id: 'supervisor', label: 'Supervisor', copy: 'A manager picks the next role from budget, failures, and uncertain quality.' },
]

const format = (value: number, digits = 2) => value.toFixed(digits)

export const App = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [scenarioId, setScenarioId] = useState('easy')
  const [strategy, setStrategy] = useState<Strategy | ''>('')
  const [seeds, setSeeds] = useState(24)
  const [seedStart, setSeedStart] = useState(1)
  const [budgetCost, setBudgetCost] = useState(160)
  const [budgetTime, setBudgetTime] = useState(220)
  const [maxIterations, setMaxIterations] = useState(40)
  const [failureRate, setFailureRate] = useState(0.05)
  const [mode, setMode] = useState<Mode>('sim')
  const [experiment, setExperiment] = useState<Experiment | null>(null)
  const [runKey, setRunKey] = useState('0')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const scenario = scenarios.find((item) => item.id === scenarioId)

  useEffect(() => {
    fetchScenarios().then(setScenarios).catch((err: Error) => setError(err.message))
    fetchHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const runningId = experiment?.status === 'running' ? experiment.id : null

  useEffect(() => {
    if (!runningId) return
    const source = new EventSource(`/api/experiments/${runningId}/events`)
    const refresh = () => {
      fetchExperiment(runningId).then(setExperiment).catch((err: Error) => setError(err.message))
    }
    source.onmessage = refresh
    const timer = window.setInterval(refresh, 1000)
    return () => {
      source.close()
      window.clearInterval(timer)
    }
  }, [runningId])

  const applyScenario = (next: Scenario, nextMode: Mode) => {
    setScenarioId(next.id)
    setFailureRate(next.failure_rate)
    setBudgetCost(next.budget_cost)
    if (nextMode === 'live') {
      setBudgetTime(720)
      setMaxIterations(16)
      setSeeds(1)
      return
    }
    setBudgetTime(next.budget_time)
    setMaxIterations(next.max_iterations)
  }

  const onMode = (next: Mode) => {
    setMode(next)
    const current = scenarios.find((item) => item.id === (next === 'live' ? 'easy' : scenarioId))
    if (!current) return
    if (next === 'live') {
      setStrategy((value) => value || 'sequential')
      applyScenario(current, 'live')
      return
    }
    applyScenario(current, 'sim')
  }

  const onRun = async () => {
    setLoading(true)
    setError(null)
    try {
      const created = await createExperiment({
        strategy: strategy || null,
        scenario_id: scenarioId,
        seeds: mode === 'live' ? 1 : seeds,
        seed_start: seedStart,
        budget_cost: budgetCost,
        budget_time: budgetTime,
        max_iterations: maxIterations,
        failure_rate: failureRate,
        mode,
      })
      setExperiment(created)
      setRunKey('0')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Experiment failed')
    } finally {
      setLoading(false)
    }
  }

  const selected = experiment?.runs[Number(runKey)] ?? experiment?.runs[0]
  const leader = useMemo(() => bestSummary(experiment?.summaries ?? []), [experiment])

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <header className="border-b border-line pb-6">
        <p className="font-mono text-xs tracking-widest text-muted uppercase">Coordination experiment</p>
        <h1 className="mt-2 text-3xl font-semibold">Agent Team Simulator</h1>
        <p className="mt-2 max-w-3xl text-muted">
          Architect, developer, tester, and reviewer share one task graph. The question is which
          coordination pattern wins on quality, cost, time, and iterations: a fixed sequence, a
          parallel team with barriers, or a supervisor.
        </p>
      </header>

      <section className="mt-6 grid gap-6 lg:grid-cols-[320px_1fr]">
        <form
          className="border border-line bg-panel p-4"
          onSubmit={(event) => {
            event.preventDefault()
            void onRun()
          }}
        >
          <fieldset className="space-y-3">
            <legend className="mb-2 font-medium">Run</legend>
            <label className="block text-sm">
              Mode
              <select className="mt-1 w-full border border-line bg-paper px-2 py-1" value={mode} onChange={(event) => onMode(event.target.value as Mode)}>
                <option value="sim">Simulation</option>
                <option value="live">Live Grok</option>
              </select>
            </label>
            <label className="block text-sm">
              Scenario
              <select
                className="mt-1 w-full border border-line bg-paper px-2 py-1"
                value={scenarioId}
                onChange={(event) => {
                  const next = scenarios.find((item) => item.id === event.target.value)
                  if (next) applyScenario(next, mode)
                }}
              >
                {scenarios.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
            <p className="text-sm text-muted">{scenario?.summary}</p>
            <label className="block text-sm">
              Strategy
              <select className="mt-1 w-full border border-line bg-paper px-2 py-1" value={strategy} onChange={(event) => setStrategy(event.target.value as Strategy | '')}>
                {STRATEGIES.filter((item) => mode === 'sim' || item.id !== '').map((item) => (
                  <option key={item.label} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <p className="text-sm text-muted">{STRATEGIES.find((item) => item.id === strategy)?.copy}</p>
            <div className="grid grid-cols-2 gap-3">
              <NumberField label="Seeds" value={seeds} disabled={mode === 'live'} onChange={setSeeds} />
              <NumberField label="First seed" value={seedStart} onChange={setSeedStart} />
              <NumberField label="Cost budget" value={budgetCost} step={1} onChange={setBudgetCost} />
              <NumberField label="Time budget" value={budgetTime} step={1} onChange={setBudgetTime} />
              <NumberField label="Max iterations" value={maxIterations} onChange={setMaxIterations} />
              <NumberField label="Failure rate" value={failureRate} step={0.01} onChange={setFailureRate} />
            </div>
          </fieldset>
          {mode === 'live' && (
            <p className="mt-3 text-sm text-warn">
              Live mode runs the bundled easy task in an isolated worktree. It calls Grok on the xAI API and stops after 12 model runs or 15 minutes.
              {health && !health.grok_api_key_configured ? ' XAI_API_KEY is not set, so a live run will fail until you add one.' : ''}
            </p>
          )}
          <button className="mt-4 w-full bg-accent px-3 py-2 text-paper disabled:opacity-60" disabled={loading || scenarios.length === 0} type="submit">
            {loading ? 'Running…' : mode === 'live' ? 'Run live pass' : 'Run experiment'}
          </button>
          {error && <p className="mt-3 text-sm text-warn">{error}</p>}
        </form>

        <section>
          {!experiment && <p className="text-muted">Run an experiment to compare the three strategies.</p>}
          {experiment && (
            <div>
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="text-xl font-medium">
                  {experiment.status === 'running' ? 'Live run in progress' : 'Results'}
                </h2>
                <p className="font-mono text-xs text-muted">{experiment.id}</p>
              </div>
              {experiment.error && <p className="mt-2 text-sm text-warn">{experiment.error}</p>}
              {leader && experiment.status === 'completed' && (
                <p className="mt-2 text-sm">
                  Highest mean quality: <span className="font-medium">{leader.strategy}</span> at {format(leader.mean_quality, 3)}
                  {' '}(95% interval {format(leader.quality_ci_low, 3)}–{format(leader.quality_ci_high, 3)}).
                </p>
              )}
              <div className="mt-4 overflow-x-auto border border-line">
                <table className="w-full border-collapse text-sm">
                  <thead className="bg-paper font-mono text-xs uppercase text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">Strategy</th>
                      <th className="px-3 py-2 text-right">Quality</th>
                      <th className="px-3 py-2 text-right">{experiment.cost_label}</th>
                      <th className="px-3 py-2 text-right">{experiment.time_label}</th>
                      <th className="px-3 py-2 text-right">Iterations</th>
                      <th className="px-3 py-2 text-right">Win rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {experiment.summaries.map((summary) => (
                      <tr key={summary.strategy} className="border-t border-line">
                        <td className="px-3 py-2 font-medium">{summary.strategy}</td>
                        <td className="px-3 py-2 text-right font-mono">{format(summary.mean_quality, 3)}</td>
                        <td className="px-3 py-2 text-right font-mono">{format(summary.mean_cost, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{format(summary.mean_time, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{format(summary.mean_iterations, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{format(summary.win_rate * 100, 0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <MetricBars summaries={experiment.summaries} />
              {experiment.runs.length > 0 && (
                <div className="mt-6">
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium">Assignment timeline</h3>
                    <label className="text-sm">
                      Run
                      <select className="ml-2 border border-line bg-panel px-2 py-1" value={runKey} onChange={(event) => setRunKey(event.target.value)}>
                        {experiment.runs.map((run, index) => (
                          <option key={`${run.strategy}-${run.seed}-${index}`} value={String(index)}>
                            {run.strategy} · seed {run.seed}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {selected && (
                    <p className="mt-2 font-mono text-xs text-muted">
                      quality {format(selected.quality, 3)} · cost {format(selected.cost, 1)} · time {format(selected.time, 1)} · iterations {selected.iterations} · rework {selected.rework_cycles} · {selected.stopped_reason}
                    </p>
                  )}
                  <ol className="mt-3 max-h-80 space-y-2 overflow-auto">
                    {selected?.events.map((event, index) => (
                      <li key={`${event.superstep}-${event.iteration}-${index}`} className="grid grid-cols-[88px_1fr] gap-3 border border-line bg-panel px-3 py-2 text-sm">
                        <span className="font-mono text-xs text-muted">step {event.superstep}</span>
                        <span>
                          <span className="font-medium">{event.role}</span>
                          {event.module_id ? ` · ${event.module_id}` : ''} · {event.outcome}
                          <span className="block text-muted">{event.detail}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}
        </section>
      </section>
    </main>
  )
}

const bestSummary = (summaries: StrategySummary[]) => {
  if (summaries.length === 0) return null
  return summaries.reduce((best, item) => (item.mean_quality > best.mean_quality ? item : best))
}

const NumberField = ({
  label,
  value,
  onChange,
  step = 1,
  disabled = false,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  step?: number
  disabled?: boolean
}) => (
  <label className="block text-sm">
    {label}
    <input
      className="mt-1 w-full border border-line bg-paper px-2 py-1 disabled:opacity-60"
      type="number"
      step={step}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  </label>
)

const MetricBars = ({ summaries }: { summaries: StrategySummary[] }) => {
  if (summaries.length === 0) return null
  const rows = [
    { label: 'Quality', read: (item: StrategySummary) => item.mean_quality },
    { label: 'Cost', read: (item: StrategySummary) => item.mean_cost },
    { label: 'Time', read: (item: StrategySummary) => item.mean_time },
    { label: 'Iterations', read: (item: StrategySummary) => item.mean_iterations },
  ]
  return (
    <div className="mt-4 grid gap-4 md:grid-cols-2">
      {rows.map((row) => {
        const max = Math.max(...summaries.map(row.read), 0.0001)
        return (
          <div key={row.label} className="border border-line bg-panel p-3">
            <p className="font-mono text-xs uppercase text-muted">{row.label}</p>
            <div className="mt-2 space-y-2">
              {summaries.map((summary) => (
                <div key={summary.strategy}>
                  <div className="flex justify-between text-xs">
                    <span>{summary.strategy}</span>
                    <span className="font-mono">{format(row.read(summary), row.label === 'Quality' ? 3 : 1)}</span>
                  </div>
                  <div className="mt-1 h-2 bg-paper">
                    <div className="h-2 bg-accent" style={{ width: `${(row.read(summary) / max) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default App
