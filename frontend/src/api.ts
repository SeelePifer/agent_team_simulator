import type { Experiment, ExperimentInput, Health, Scenario } from './types'

export const fetchScenarios = async (): Promise<Scenario[]> => {
  const response = await fetch('/api/scenarios')
  if (!response.ok) throw new Error('Could not load scenarios')
  return response.json()
}

export const fetchHealth = async (): Promise<Health> => {
  const response = await fetch('/api/health')
  if (!response.ok) throw new Error('Could not reach the API')
  return response.json()
}

export const createExperiment = async (input: ExperimentInput): Promise<Experiment> => {
  const response = await fetch('/api/experiments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    const detail = payload.detail
    if (typeof detail === 'string') throw new Error(detail)
    if (Array.isArray(detail)) {
      const message = detail.map((item: { msg?: string }) => item.msg ?? 'Invalid request').join(' ')
      throw new Error(message)
    }
    throw new Error('Experiment failed')
  }
  return response.json()
}

export const fetchExperiment = async (id: string): Promise<Experiment> => {
  const response = await fetch(`/api/experiments/${id}`)
  if (!response.ok) throw new Error('Experiment not found')
  return response.json()
}
