import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatDate, formatDuration } from '../api/format'
import { useRuns } from '../api/hooks'
import type { Run } from '../api/types'
import { useProject } from '../app/project'
import { ConfirmDialog } from '../components/Dialog'
import { ActionError, Hash, Progress } from '../components/Misc'
import { Content, PageHeader } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { StatusBadge } from '../components/Status'
import { useToast } from '../components/Toast'
import { errorCount } from './OverviewPage'

const STATUSES = ['queued', 'running', 'cancelling', 'completed', 'completed_with_errors', 'cancelled', 'failed']
const ACTIVE = ['queued', 'running', 'cancelling']

export function RunsPage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const [search, setSearch] = useState('')
  const [cancelling, setCancelling] = useState<Run | null>(null)
  const query = useRuns(projectId, status || undefined)
  const queryClient = useQueryClient()
  const toast = useToast()
  const cancel = useMutation({
    mutationFn: (run: Run) => api.post<Run>(`/runs/${run.id}/cancel`),
    onSuccess: () => {
      setCancelling(null)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      toast('Cancellation requested. Finished trials are kept; the run stays visible.')
    },
  })
  const runs = (query.data?.data ?? []).filter((r) => !search || (r.name || r.id).toLowerCase().includes(search.toLowerCase()))

  return (
    <>
      <PageHeader
        title="Runs"
        subtitle="Every run keeps its manifest; cancelled runs remain visible."
        actions={
          <Link to="/runs/new" className="btn btn-primary">
            Set up a run
          </Link>
        }
      />
      <Content>
        <div className="row" role="search">
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="run-status">Status</label>
            <select
              id="run-status"
              value={status}
              onChange={(e) => {
                const next = new URLSearchParams(params)
                if (e.target.value) next.set('status', e.target.value)
                else next.delete('status')
                setParams(next, { replace: true })
              }}
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 260 }}>
            <label htmlFor="run-search">Name contains</label>
            <input id="run-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        {query.isPending ? (
          <Loading />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : runs.length === 0 ? (
          <Empty title={status || search ? 'No runs match these filters' : 'No runs yet'} action={<Link to="/runs/new" className="btn">Set up a run</Link>}>
            Runs are created from Run setup after validation.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th className="num">Target errors</th>
                  <th>Candidates</th>
                  <th className="num">Repeats</th>
                  <th>Manifest</th>
                  <th>Created</th>
                  <th>Time</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} data-testid="run-row">
                    <td>
                      <Link to={`/runs/${run.id}`}>{run.name || run.id.slice(0, 8)}</Link>
                      {run.parent_run_id && <div className="tiny muted">linked to an earlier run</div>}
                      {run.is_demo && <div className="tiny muted">demo</div>}
                    </td>
                    <td>
                      <StatusBadge kind="run" value={run.status} />
                    </td>
                    <td style={{ minWidth: 150 }}>
                      <Progress value={run.terminal_trials} max={run.planned_trial_count} label={`${run.name} progress`} />
                    </td>
                    <td className="num">{errorCount(run)}</td>
                    <td className="small">{run.candidates.map((c) => c.name ?? c.key).join(' vs ')}</td>
                    <td className="num">{run.repeats ?? '—'}</td>
                    <td>
                      <Hash value={run.manifest_hash} />
                    </td>
                    <td className="small nowrap">{formatDate(run.created_at)}</td>
                    <td className="small nowrap">{formatDuration(run.started_at, run.finished_at)}</td>
                    <td>
                      <div className="row" style={{ flexWrap: 'nowrap' }}>
                        <Link className="btn btn-sm" to={`/runs/new?clone=${run.id}`}>
                          Clone setup
                        </Link>
                        {ACTIVE.includes(run.status) && run.status !== 'cancelling' && (
                          <button type="button" className="btn btn-sm btn-danger" onClick={() => setCancelling(run)}>
                            Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {typeof query.data?.meta.next_cursor === 'string' && <p className="muted small">Showing the 100 most recent runs.</p>}
        <ActionError error={cancel.error} />
      </Content>
      <ConfirmDialog
        open={!!cancelling}
        onOpenChange={(open) => !open && setCancelling(null)}
        title="Cancel this run?"
        description={
          <>
            Pending trials will not start. Trials already running finish and are recorded as late results. The run can never be
            marked ready.
          </>
        }
        confirmLabel="Cancel run"
        busy={cancel.isPending}
        onConfirm={() => cancelling && cancel.mutate(cancelling)}
      />
    </>
  )
}
