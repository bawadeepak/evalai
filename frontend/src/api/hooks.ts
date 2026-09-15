// TanStack Query hooks for every resource the UI reads. Mutations live next to
// the pages that use them; these hooks own caching keys only.

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type Params } from './client'
import type {
  AdapterInfo,
  Adjudicated,
  Calibration,
  Case,
  Comparison,
  ConnectionTest,
  Dataset,
  DatasetDetail,
  ExportRecord,
  Grader,
  Health,
  Job,
  Packs,
  ProbabilityEvent,
  ProbabilityQuality,
  ProbabilityRecord,
  Project,
  ReleasePolicy,
  Representation,
  Review,
  Run,
  RunSummary,
  Scenario,
  ScenarioDetail,
  SettingsInfo,
  TargetConfig,
  TrialBrief,
  TrialDetail,
  TriageQueue,
} from './types'

const data = <T>(promise: Promise<{ data: T }>) => promise.then((r) => r.data)

export const keys = {
  health: ['health'] as const,
  projects: ['projects'] as const,
  runs: (projectId: string | null, status?: string) => ['runs', projectId, status ?? ''] as const,
  run: (id: string) => ['run', id] as const,
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: () => data(api.get<Health>('/health')), refetchInterval: 5000, retry: false })
}

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: () => data(api.get<Project[]>('/projects')) })
}

export function usePacks() {
  return useQuery({ queryKey: ['packs'], queryFn: () => data(api.get<Packs>('/packs')), staleTime: Infinity })
}

export function useAdapters() {
  return useQuery({ queryKey: ['adapters'], queryFn: () => data(api.get<AdapterInfo[]>('/adapters')) })
}

export function useScenarios(projectId: string | null, latestOnly = true) {
  return useQuery({
    queryKey: ['scenarios', projectId, latestOnly],
    queryFn: () => data(api.get<Scenario[]>('/scenarios', { project_id: projectId, latest_only: latestOnly })),
    enabled: !!projectId,
  })
}

export function useScenario(id: string | null | undefined) {
  return useQuery({ queryKey: ['scenario', id], queryFn: () => data(api.get<ScenarioDetail>(`/scenarios/${id}`)), enabled: !!id })
}

export function useDatasets(projectId: string | null, scenarioId?: string | null) {
  return useQuery({
    queryKey: ['datasets', projectId, scenarioId ?? ''],
    queryFn: () => data(api.get<Dataset[]>('/datasets', { project_id: projectId, scenario_id: scenarioId })),
    enabled: !!projectId,
  })
}

export function useDataset(id: string | null | undefined) {
  return useQuery({ queryKey: ['dataset', id], queryFn: () => data(api.get<DatasetDetail>(`/datasets/${id}`)), enabled: !!id })
}

export function useCases(datasetId: string | null | undefined, params: Params = {}) {
  return useQuery({
    queryKey: ['cases', datasetId, params],
    queryFn: () => api.get<Case[]>(`/datasets/${datasetId}/cases`, params),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
  })
}

export function useTargets(projectId: string | null) {
  return useQuery({
    queryKey: ['targets', projectId],
    queryFn: () => data(api.get<TargetConfig[]>('/target-configs', { project_id: projectId })),
    enabled: !!projectId,
  })
}

export function useConnectionTest(id: string | null) {
  return useQuery({
    queryKey: ['connection-test', id],
    queryFn: () => data(api.get<ConnectionTest>(`/connection-tests/${id}`)),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data && !['queued', 'running'].includes(query.state.data.status) ? false : 1000),
  })
}

export function useGraders(projectId: string | null) {
  return useQuery({
    queryKey: ['graders', projectId],
    queryFn: () => data(api.get<Grader[]>('/graders', { project_id: projectId })),
    enabled: !!projectId,
  })
}

const ACTIVE = ['queued', 'running', 'cancelling']

export function useRuns(projectId: string | null, status?: string) {
  return useQuery({
    queryKey: keys.runs(projectId, status),
    queryFn: () => api.get<Run[]>('/runs', { project_id: projectId, status, limit: 100 }),
    enabled: !!projectId,
    refetchInterval: (query) => (query.state.data?.data.some((r) => ACTIVE.includes(r.status)) ? 2000 : false),
  })
}

export function useRun(id: string | null | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ''),
    queryFn: () => data(api.get<Run>(`/runs/${id}`)),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data && ACTIVE.includes(query.state.data.status) ? 3000 : false),
  })
}

export function useRunSummary(id: string | null | undefined, representation: Representation = 'raw', gradingRunId?: string | null) {
  return useQuery({
    queryKey: ['summary', id, representation, gradingRunId ?? ''],
    queryFn: () => data(api.get<RunSummary>(`/runs/${id}/summary`, { representation, grading_run_id: gradingRunId })),
    enabled: !!id,
    placeholderData: keepPreviousData,
  })
}

export function useTriage(runId: string | null | undefined, filters: Params = {}) {
  return useQuery({
    queryKey: ['triage', runId, filters],
    queryFn: () => data(api.get<TriageQueue>(`/runs/${runId}/triage`, filters)),
    enabled: !!runId,
    placeholderData: keepPreviousData,
  })
}

export function useRunTrials(runId: string | null | undefined) {
  return useQuery({
    queryKey: ['trials', runId],
    queryFn: () => data(api.get<TrialBrief[]>(`/runs/${runId}/trials`, { limit: 2000 })),
    enabled: !!runId,
  })
}

export function useTrial(id: string | null | undefined) {
  return useQuery({ queryKey: ['trial', id], queryFn: () => data(api.get<TrialDetail>(`/trials/${id}`)), enabled: !!id })
}

export function useAdjudicated(id: string | null | undefined) {
  return useQuery({ queryKey: ['adjudicated', id], queryFn: () => data(api.get<Adjudicated>(`/trials/${id}/adjudicated`)), enabled: !!id })
}

export function useReviews(params: Params, enabled = true) {
  return useQuery({ queryKey: ['reviews', params], queryFn: () => data(api.get<Review[]>('/reviews', params)), enabled })
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: () => data(api.get<SettingsInfo>('/settings')) })
}

export function useProbabilityEvents(projectId: string | null) {
  return useQuery({
    queryKey: ['prob-events', projectId],
    queryFn: () => data(api.get<ProbabilityEvent[]>('/probability/events', { project_id: projectId })),
    enabled: !!projectId,
  })
}

export function useProbabilityQuality(params: Params, enabled: boolean) {
  return useQuery({
    queryKey: ['prob-quality', params],
    queryFn: () => data(api.get<ProbabilityQuality>('/probability/quality', params)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

export function useProbabilityRecords(params: Params, enabled: boolean) {
  return useQuery({
    queryKey: ['prob-records', params],
    queryFn: () => api.get<ProbabilityRecord[]>('/probability/records', params),
    enabled,
  })
}

export function useCalibrations(projectId: string | null, eventDefinition?: string | null) {
  return useQuery({
    queryKey: ['calibrations', projectId, eventDefinition ?? ''],
    queryFn: () => data(api.get<Calibration[]>('/calibrations', { project_id: projectId, event_definition: eventDefinition })),
    enabled: !!projectId,
  })
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => data(api.get<Job>(`/jobs/${id}`)),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data && !['queued', 'running'].includes(query.state.data.status) ? false : 800),
  })
}

export function useComparisons(projectId: string | null) {
  return useQuery({
    queryKey: ['comparisons', projectId],
    queryFn: () => data(api.get<Comparison[]>('/comparisons', { project_id: projectId })),
    enabled: !!projectId,
  })
}

export function useReleasePolicies(projectId: string | null) {
  return useQuery({
    queryKey: ['policies', projectId],
    queryFn: () => data(api.get<ReleasePolicy[]>('/release-policies', { project_id: projectId })),
    enabled: !!projectId,
  })
}

export function useExports(projectId: string | null) {
  return useQuery({
    queryKey: ['exports', projectId],
    queryFn: () => data(api.get<ExportRecord[]>('/exports', { project_id: projectId })),
    enabled: !!projectId,
    refetchInterval: (query) => (query.state.data?.some((e) => ['queued', 'running'].includes(e.status)) ? 1000 : false),
  })
}
