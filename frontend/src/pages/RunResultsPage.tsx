// Results: summary counts, the case × candidate matrix with trial strips, and
// slices. Every number links to the trials it came from.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { formatDate, formatDuration, formatMs, formatSigned } from '../api/format'
import { useRun, useRunSummary } from '../api/hooks'
import type { Representation, RunSummary, SummaryCase } from '../api/types'
import { Dialog } from '../components/Dialog'
import { MetricValue } from '../components/MetricValue'
import { ActionError, Hash, KeyValue, Progress } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { Disconnected, Empty, ErrorState, Loading, Partial } from '../components/States'
import { Badge, SeverityBadge, StatusBadge } from '../components/Status'
import { TileLegend, TrialStrip } from '../components/TrialStrip'
import { useToast } from '../components/Toast'
import { useRunEvents } from '../hooks/useRunEvents'

export const REPRESENTATIONS: Record<Representation, string> = {
  raw: 'Raw text — repeats agree only when the output text is identical.',
  json: 'Canonical JSON — outputs are parsed and compared with sorted keys; unparsable outputs are ineligible and counted.',
  semantic: 'Semantic class (semantic:pass_rule_outcome_v1) — repeats agree when they reach the same pass-rule outcome.',
}

const ACTIVE = ['queued', 'running', 'cancelling']
type Filter = 'failures' | 'flaky' | 'changed' | 'incomplete'

export function caseMatches(c: SummaryCase, filters: Set<Filter>, repeats: number | null): boolean {
  const cands = Object.values(c.candidates)
  if (filters.has('failures') && !cands.some((x) => x.counts.fails > 0)) return false
  if (filters.has('flaky') && !cands.some((x) => x.flags.flaky)) return false
  if (filters.has('changed') && !c.changed) return false
  if (
    filters.has('incomplete') &&
    !cands.some((x) => (x.statuses.pending ?? 0) + (x.statuses.running ?? 0) > 0 || x.counts.unresolved > 0 || (repeats !== null && x.counts.trials < repeats))
  )
    return false
  return true
}

function SlotRates({ summary, runId }: { summary: RunSummary; runId: string }) {
  return (
    <div className="grid grid-2">
      {summary.candidates.map((key) => {
        const s = summary.slot_rates[key]
        if (!s) return null
        return (
          <Section key={key} title={`${key}${key === summary.baseline ? ' (baseline)' : ''}`} id={`slots-${key}`}>
            <p className="small muted" style={{ marginTop: -6 }}>
              Scheduled {s.scheduled} · generated {s.generated} · graded {s.graded} · passed {s.passed} · failed {s.failed} · unresolved {s.unresolved}
            </p>
            <div className="grid grid-2">
              <div>
                <div className="kpi-label">Target completion (G / S)</div>
                <MetricValue metric={s.target_completion} runId={runId} />
              </div>
              <div>
                <div className="kpi-label">Grade coverage</div>
                <MetricValue metric={s.grade_coverage} runId={runId} />
              </div>
              <div>
                <div className="kpi-label">Conditional pass (P / (P + F))</div>
                <MetricValue metric={s.conditional_pass} runId={runId} />
              </div>
              <div>
                <div className="kpi-label">Observed success yield (P / S)</div>
                <MetricValue metric={s.observed_success_yield} runId={runId} />
              </div>
              <div>
                <div className="kpi-label">Latency p50 / p95</div>
                <span className="metric-value num">
                  {s.latency.p50_ms === null ? 'Unavailable' : `${formatMs(s.latency.p50_ms)} / ${formatMs(s.latency.p95_ms)}`}
                </span>
                <div className="metric-sub">
                  {s.latency.count} completed calls · {s.latency.timeouts} timeouts{s.latency.reason ? ` · ${s.latency.reason}` : ''}
                </div>
              </div>
              <div>
                <div className="kpi-label">Invariant failures</div>
                <span className="metric-value num">{Object.values(s.invariant_failures).reduce((a, b) => a + b, 0)}</span>
              </div>
            </div>
          </Section>
        )
      })}
    </div>
  )
}

function Matrix({ summary, runId, repeats, selected, setSelected }: {
  summary: RunSummary
  runId: string
  repeats: number | null
  selected: Set<string>
  setSelected: (next: Set<string>) => void
}) {
  const [filters, setFilters] = useState<Set<Filter>>(new Set())
  const baseline = summary.baseline
  const others = summary.candidates.filter((c) => c !== baseline)
  const rows = summary.cases.filter((c) => caseMatches(c, filters, repeats))
  const toggleFilter = (f: Filter) => {
    const next = new Set(filters)
    if (next.has(f)) next.delete(f)
    else next.add(f)
    setFilters(next)
  }
  return (
    <>
      <div className="row" role="group" aria-label="Filter cases">
        {(['failures', 'flaky', 'changed', 'incomplete'] as Filter[]).map((f) => (
          <button key={f} type="button" className="btn btn-sm" aria-pressed={filters.has(f)} onClick={() => toggleFilter(f)}>
            {f === 'changed' ? 'Changed vs baseline' : f[0]!.toUpperCase() + f.slice(1)}
          </button>
        ))}
        <span className="small muted">
          {rows.length} of {summary.cases.length} cases
        </span>
      </div>
      <TileLegend />
      {rows.length === 0 ? (
        <Empty title="No cases match these filters" />
      ) : (
        <div className="table-wrap" style={{ maxHeight: '70vh' }}>
          <table data-testid="results-matrix">
            <thead>
              <tr>
                <th className="sticky-col" style={{ minWidth: 30 }}>
                  <span className="sr-only">Select</span>
                </th>
                <th className="sticky-col" style={{ left: 38, minWidth: 70 }}>
                  Case
                </th>
                <th>Severity</th>
                <th style={{ minWidth: 200 }}>Purpose</th>
                {baseline && <th className="num">Baseline pass</th>}
                {others.map((key) => (
                  <th key={`${key}-p`} className="num">
                    {key} pass
                  </th>
                ))}
                {baseline &&
                  others.map((key) => (
                    <th key={`${key}-d`} className="num">
                      Δ {key}
                    </th>
                  ))}
                {others.map((key) => (
                  <th key={`${key}-m`} className="num">
                    Modal agr. ({key})
                  </th>
                ))}
                {others.map((key) => (
                  <th key={`${key}-a`} className="num">
                    Pairwise agr. ({key})
                  </th>
                ))}
                {others.map((key) => (
                  <th key={`${key}-l`} className="num">
                    p50 ({key})
                  </th>
                ))}
                <th className="num">Errors</th>
                <th>Review</th>
                <th style={{ minWidth: 260 }}>Trials</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const errors = Object.values(c.candidates).reduce((sum, x) => sum + x.counts.errors + x.counts.provider_errors + x.counts.invalid_outputs, 0)
                const firstOther = others[0] ?? summary.candidates[0]
                return (
                  <tr key={c.case_id} data-testid={`case-row-${c.external_id}`}>
                    <td className="sticky-col">
                      <input
                        type="checkbox"
                        aria-label={`Select ${c.external_id} for more trials`}
                        checked={selected.has(c.case_id)}
                        onChange={(e) => {
                          const next = new Set(selected)
                          if (e.target.checked) next.add(c.case_id)
                          else next.delete(c.case_id)
                          setSelected(next)
                        }}
                      />
                    </td>
                    <td className="sticky-col" style={{ left: 38 }}>
                      <Link to={`/triage?run=${runId}&case=${c.case_id}&candidate=${firstOther}`}>{c.external_id}</Link>
                    </td>
                    <td>
                      <SeverityBadge severity={c.severity} />
                    </td>
                    <td className="small">{c.purpose}</td>
                    {baseline && (
                      <td className="num">
                        <MetricValue metric={c.candidates[baseline]?.metrics.pass_rate} label={`${c.external_id} baseline pass rate`} runId={runId} showInterval={false} />
                      </td>
                    )}
                    {others.map((key) => (
                      <td key={`${key}-p`} className="num">
                        <MetricValue metric={c.candidates[key]?.metrics.pass_rate} label={`${c.external_id} ${key} pass rate`} runId={runId} showInterval={false} />
                      </td>
                    ))}
                    {baseline &&
                      others.map((key) => (
                        <td key={`${key}-d`} className="num">
                          {formatSigned(c.delta_vs_baseline[key] ?? null, 'fraction')}
                        </td>
                      ))}
                    {others.map((key) => (
                      <td key={`${key}-m`} className="num">
                        <MetricValue metric={c.candidates[key]?.metrics.modal_agreement} runId={runId} showCounts={false} />
                      </td>
                    ))}
                    {others.map((key) => (
                      <td key={`${key}-a`} className="num">
                        <MetricValue metric={c.candidates[key]?.metrics.pairwise_agreement} runId={runId} showCounts={false} />
                      </td>
                    ))}
                    {others.map((key) => (
                      <td key={`${key}-l`} className="num">
                        <MetricValue metric={c.candidates[key]?.metrics.latency_p50} runId={runId} showCounts={false} />
                      </td>
                    ))}
                    <td className="num">{errors}</td>
                    <td>
                      <Badge tone={c.review.state === 'unreviewed' ? 'na' : 'info'}>{c.review.state.replace(/_/g, ' ')}</Badge>
                    </td>
                    <td>
                      <div className="stack" style={{ gap: 4 }}>
                        {summary.candidates.map((key) => (
                          <div key={key} className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                            <span className="tiny muted" style={{ width: 64, flex: 'none' }}>
                              {key}
                            </span>
                            <TrialStrip trials={c.candidates[key]?.trials ?? []} runId={runId} label={`${c.external_id} ${key}`} />
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function MoreTrialsDialog({ runId, caseIds, open, onOpenChange }: { runId: string; caseIds: string[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [repeats, setRepeats] = useState(5)
  const [key] = useState(newIdempotencyKey)
  const navigate = useNavigate()
  const toast = useToast()
  const create = useMutation({
    mutationFn: () => api.post<{ id: string; sampling_note: string }>(`/runs/${runId}/more-trials`, { case_ids: caseIds, repeats }, { 'Idempotency-Key': `${key}-${repeats}-${caseIds.join(',')}` }),
    onSuccess: ({ data }) => {
      toast(data.sampling_note)
      onOpenChange(false)
      navigate(`/runs/${data.id}`)
    },
  })
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`More trials for ${caseIds.length} case${caseIds.length === 1 ? '' : 's'}`}
      description="Creates a linked run with fresh repeats. The original results are unchanged; combined analysis must state that these trials were requested after inspecting results."
      footer={
        <button type="button" className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending || repeats < 1}>
          Create linked run
        </button>
      }
    >
      <Field id="more-repeats" label="Repeats per case">
        {(props) => <input {...props} type="number" min={1} max={200} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} />}
      </Field>
      <ActionError error={create.error} />
    </Dialog>
  )
}

export function RunResultsPage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const representation = (params.get('representation') as Representation) || 'raw'
  const gradingRunId = params.get('grading')
  const run = useRun(id)
  const active = !!run.data && ACTIVE.includes(run.data.status)
  const summary = useRunSummary(id, representation, gradingRunId)
  const stream = useRunEvents(id, active)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [moreOpen, setMoreOpen] = useState(false)
  const queryClient = useQueryClient()
  const toast = useToast()
  const regrade = useMutation({
    mutationFn: () => api.post<{ id: string; note: string }>('/grading-runs', { run_id: id, grader_ids: run.data?.grading_runs[0]?.grader_ids ?? [] }),
    onSuccess: ({ data }) => {
      toast(data.note)
      void queryClient.invalidateQueries({ queryKey: ['run', id] })
    },
  })
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const cancelCount = useMemo(() => (run.data ? Object.entries(run.data.trial_counts).filter(([k]) => k !== 'success').reduce((a, [, v]) => a + v, 0) : 0), [run.data])

  if (run.isPending)
    return (
      <>
        <PageHeader title="Run results" />
        <Content>
          <Loading />
        </Content>
      </>
    )
  if (run.isError)
    return (
      <>
        <PageHeader title="Run results" />
        <Content>
          <ErrorState error={run.error} onRetry={() => void run.refetch()} />
        </Content>
      </>
    )
  const r = run.data
  const baselineKey = r.candidates.find((c) => c.key === 'baseline')?.key ?? r.candidates[0]?.key
  const candidateKey = r.candidates.find((c) => c.key !== baselineKey)?.key ?? baselineKey
  return (
    <>
      <PageHeader
        title={r.name || `Run ${r.id.slice(0, 8)}`}
        subtitle={
          <span className="row">
            <StatusBadge kind="run" value={r.status} />
            <span>
              {r.manifest?.scenario.name} v{r.manifest?.scenario.version} · {r.manifest?.dataset.name} v{r.manifest?.dataset.version} · {r.repeats} repeats
            </span>
          </span>
        }
        actions={
          <>
            <Link className="btn" to={`/triage?run=${r.id}`}>
              Triage
            </Link>
            {r.candidates.length > 1 && (
              <Link className="btn" to={`/compare?baseline=${r.id}&baseline_key=${baselineKey}&candidate=${r.id}&candidate_key=${candidateKey}`}>
                Compare
              </Link>
            )}
            <button type="button" className="btn" onClick={() => regrade.mutate()} disabled={active || regrade.isPending}>
              Regrade stored outputs
            </button>
            <Link className="btn" to={`/runs/new?clone=${r.id}`}>
              Clone setup
            </Link>
          </>
        }
      />
      <Content>
        {r.demo_notice && <p className="notice warn small">{r.demo_notice}</p>}
        {active && stream.state === 'reconnecting' && <Disconnected>Live progress disconnected. Reconnecting — the snapshot below refreshes every few seconds.</Disconnected>}
        {r.parent_run_id && (
          <p className="notice info small">
            Linked run with fresh repeats requested after inspecting <Link to={`/runs/${r.parent_run_id}`}>the original run</Link>. Its results are
            reported separately.
          </p>
        )}
        <ActionError error={regrade.error} />
        <Section title="Progress" id="progress">
          <div className="stack">
            <Progress value={r.terminal_trials} max={r.planned_trial_count} label="Trials finished" />
            <KeyValue
              items={[
                ['Trial statuses', Object.entries(r.trial_counts).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(' · ') || 'none yet'],
                ['Non-success trials', cancelCount],
                ['Started', formatDate(r.started_at)],
                ['Elapsed', formatDuration(r.started_at, r.finished_at)],
                ['Manifest', <Hash key="m" value={r.manifest_hash} />],
                ['Grading runs', r.grading_runs.map((g) => `${g.source} (${g.status})`).join(', ')],
              ]}
            />
            {r.warnings.map((w) => (
              <p key={w} className="notice warn small">
                {w}
              </p>
            ))}
          </div>
        </Section>
        <div className="row">
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="representation">Agreement representation</label>
            <select id="representation" value={representation} onChange={(e) => setParam('representation', e.target.value === 'raw' ? null : e.target.value)}>
              <option value="raw">Raw text</option>
              <option value="json">Canonical JSON</option>
              <option value="semantic">Semantic class</option>
            </select>
          </div>
          {r.grading_runs.length > 1 && (
            <div className="field" style={{ width: 260 }}>
              <label htmlFor="grading-run">Grading run</label>
              <select id="grading-run" value={gradingRunId ?? ''} onChange={(e) => setParam('grading', e.target.value || null)}>
                <option value="">Latest</option>
                {r.grading_runs.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.source} · {formatDate(g.created_at)} · {g.status}
                  </option>
                ))}
              </select>
            </div>
          )}
          <p className="small muted grow" style={{ alignSelf: 'flex-end', margin: 0 }} data-testid="representation-definition">
            {REPRESENTATIONS[representation]}
          </p>
        </div>
        {summary.isPending ? (
          <Loading />
        ) : summary.isError ? (
          <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
        ) : (
          <>
            {active && <Partial>Run in progress: counts below include only finished trials and update live.</Partial>}
            <SlotRates summary={summary.data} runId={r.id} />
            <Section
              title="Cases"
              id="matrix"
              actions={
                <button type="button" className="btn btn-sm" disabled={selected.size === 0} onClick={() => setMoreOpen(true)}>
                  More trials ({selected.size})
                </button>
              }
            >
              <Matrix summary={summary.data} runId={r.id} repeats={r.repeats} selected={selected} setSelected={setSelected} />
              {summary.data.notes.map((n) => (
                <p key={n} className="small muted" style={{ marginTop: 8 }}>
                  {n}
                </p>
              ))}
            </Section>
            {summary.data.slices.length > 0 && (
              <Section title="Slices" id="slices">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Slice</th>
                        {summary.data.candidates.map((k) => (
                          <th key={k} className="num">
                            {k} pass rate
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {summary.data.slices.map((s) => (
                        <tr key={`${s.key}=${s.value}`}>
                          <td>
                            {s.key} = {s.value}
                          </td>
                          {summary.data.candidates.map((k) => (
                            <td key={k} className="num">
                              <MetricValue metric={s.candidates[k]} runId={r.id} />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            )}
          </>
        )}
      </Content>
      <MoreTrialsDialog runId={r.id} caseIds={[...selected]} open={moreOpen} onOpenChange={setMoreOpen} />
    </>
  )
}
