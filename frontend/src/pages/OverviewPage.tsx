import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { formatDate } from '../api/format'
import { useRuns, useTriage } from '../api/hooks'
import type { Project, Run } from '../api/types'
import { useProject } from '../app/project'
import { ActionError, Progress } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { SeverityBadge, StatusBadge } from '../components/Status'
import { useToast } from '../components/Toast'

type DemoResult = { project_id: string; runs: { suite: string; run_id: string; planned_trials: number }[]; note: string }

const ACTIVE = ['queued', 'running', 'cancelling']
const TARGET_ERRORS = ['provider_error', 'timeout', 'invalid_output', 'interrupted', 'unsupported']

export function errorCount(run: Run): number {
  return TARGET_ERRORS.reduce((sum, key) => sum + (run.trial_counts[key] ?? 0), 0)
}

function useLoadDemo() {
  const queryClient = useQueryClient()
  const { setProjectId } = useProject()
  const toast = useToast()
  return useMutation({
    mutationFn: () => api.post<DemoResult>('/demo'),
    onSuccess: ({ data }) => {
      setProjectId(data.project_id)
      void queryClient.invalidateQueries()
      toast('Labelled demo loaded. Its runs execute while a worker is running.')
    },
  })
}

function CreateProject() {
  const [name, setName] = useState('')
  const queryClient = useQueryClient()
  const { setProjectId } = useProject()
  const create = useMutation({
    mutationFn: () => api.post<Project>('/projects', { name }),
    onSuccess: ({ data }) => {
      setProjectId(data.id)
      setName('')
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  return (
    <form
      className="row"
      style={{ alignItems: 'flex-end' }}
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) create.mutate()
      }}
    >
      <Field id="new-project-name" label="New project name">
        {(props) => <input {...props} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Support assistant" />}
      </Field>
      <button type="submit" className="btn" disabled={!name.trim() || create.isPending}>
        Create project
      </button>
      <ActionError error={create.error} />
    </form>
  )
}

function Onboarding({ compact }: { compact?: boolean }) {
  const demo = useLoadDemo()
  return (
    <Section title={compact ? 'Get started' : 'Welcome to Eval Triage'} id="onboarding">
      {!compact && (
        <p className="muted">
          Evaluate LLM calls, RAG, agents and MemoryAI with case-level evidence. Quality, repeatability, probability quality
          and operations are reported separately.
        </p>
      )}
      <div className="row">
        <Link className="btn" to="/scenarios/new">
          Create scenario
        </Link>
        <Link className="btn" to="/datasets?import=1">
          Import dataset
        </Link>
        <Link className="btn" to="/providers?new=1">
          Configure provider
        </Link>
        <button type="button" className="btn btn-accent" onClick={() => demo.mutate()} disabled={demo.isPending}>
          {demo.isPending ? 'Loading demo…' : 'Load labelled demo'}
        </button>
      </div>
      <ActionError error={demo.error} />
      {!compact && (
        <div style={{ marginTop: 14 }}>
          <CreateProject />
        </div>
      )}
    </Section>
  )
}

function CriticalRegressions({ run }: { run: Run }) {
  const triage = useTriage(run.id)
  const items = useMemo(
    () => (triage.data?.items ?? []).filter((i) => i.priority === 0 || (i.flags.regression && i.severity === 'critical')),
    [triage.data],
  )
  if (triage.isPending) return <Loading lines={2} />
  if (triage.isError) return <ErrorState error={triage.error} onRetry={() => void triage.refetch()} />
  if (!items.length) return <p className="muted">No critical failures or critical regressions in “{run.name}”.</p>
  return (
    <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {items.map((item) => (
        <li key={`${item.case_id}-${item.candidate_key}`} className="row-between">
          <span className="row">
            <SeverityBadge severity={item.severity} />
            <Link to={`/triage?run=${run.id}&case=${item.case_id}&candidate=${item.candidate_key}`}>
              {item.external_id} · {item.candidate_key}
            </Link>
            <span className="muted small">{item.priority_label}</span>
          </span>
          <span className="num small">
            {item.counts.passes} / {item.counts.trials} pass
          </span>
        </li>
      ))}
    </ul>
  )
}

export function OverviewPage() {
  const { project, projectId, projects, isPending, error, refetch } = useProject()
  const runsQuery = useRuns(projectId)
  const runs = runsQuery.data?.data ?? []
  const active = runs.filter((r) => ACTIVE.includes(r.status))
  const latestFinished = runs.find((r) => r.status.startsWith('completed') && r.candidates.length > 1) ?? null

  if (isPending) {
    return (
      <>
        <PageHeader title="Overview" />
        <Content>
          <Loading />
        </Content>
      </>
    )
  }
  if (error) {
    return (
      <>
        <PageHeader title="Overview" />
        <Content>
          <ErrorState error={error} onRetry={refetch} />
        </Content>
      </>
    )
  }
  if (!projects.length) {
    return (
      <>
        <PageHeader title="Overview" subtitle="No projects yet" />
        <Content>
          <Onboarding />
        </Content>
      </>
    )
  }

  const trialsDone = runs.reduce((sum, r) => sum + r.terminal_trials, 0)
  const targetErrors = runs.reduce((sum, r) => sum + errorCount(r), 0)
  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={project?.name}
        actions={
          <Link to="/runs/new" className="btn btn-primary">
            Set up a run
          </Link>
        }
      />
      <Content>
        <div className="kpis" aria-label="Project totals">
          <div className="kpi">
            <div className="kpi-label">Runs</div>
            <div className="metric-value num">{runs.length}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Active runs</div>
            <div className="metric-value num">{active.length}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Trials finished</div>
            <div className="metric-value num">{trialsDone}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Target errors (all runs)</div>
            <div className="metric-value num">{targetErrors}</div>
          </div>
        </div>
        <div className="grid grid-2">
          <Section title="Active jobs" id="active-jobs">
            {active.length === 0 ? (
              <p className="muted">No runs are queued or running.</p>
            ) : (
              <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {active.map((run) => (
                  <li key={run.id} className="stack" style={{ gap: 4 }}>
                    <div className="row-between">
                      <Link to={`/runs/${run.id}`}>{run.name || run.id.slice(0, 8)}</Link>
                      <StatusBadge kind="run" value={run.status} />
                    </div>
                    <Progress value={run.terminal_trials} max={run.planned_trial_count} label={`${run.name} progress`} />
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="Critical regressions" id="critical">
            {latestFinished ? <CriticalRegressions run={latestFinished} /> : <p className="muted">No finished comparison run yet.</p>}
          </Section>
        </div>
        <Section
          title="Recent runs"
          id="recent-runs"
          actions={
            <Link to="/runs" className="btn btn-sm">
              All runs
            </Link>
          }
        >
          {runsQuery.isPending ? (
            <Loading />
          ) : runsQuery.isError ? (
            <ErrorState error={runsQuery.error} onRetry={() => void runsQuery.refetch()} />
          ) : runs.length === 0 ? (
            <Empty title="No runs yet" action={<Link to="/runs/new" className="btn">Set up a run</Link>}>
              A run executes every case × candidate × repeat and grades the stored outputs.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Completion</th>
                    <th className="num">Target errors</th>
                    <th>Grading</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.slice(0, 8).map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link to={`/runs/${run.id}`}>{run.name || run.id.slice(0, 8)}</Link>
                      </td>
                      <td>
                        <StatusBadge kind="run" value={run.status} />
                      </td>
                      <td style={{ minWidth: 160 }}>
                        <Progress value={run.terminal_trials} max={run.planned_trial_count} label={`${run.name} completion`} />
                      </td>
                      <td className="num">{errorCount(run)}</td>
                      <td className="small">{run.grading_runs.at(-1)?.status.replace(/_/g, ' ') ?? '—'}</td>
                      <td className="small nowrap">{formatDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
        <Onboarding compact />
      </Content>
    </>
  )
}
