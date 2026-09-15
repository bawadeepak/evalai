// Triage: prioritised failure queue, exact evidence and review. Selection and
// filters live in the URL so evidence can be bookmarked; J/K/Enter/Esc work
// when not typing.

import { useEffect, useMemo, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useRunSummary, useRuns, useTrial, useTriage } from '../api/hooks'
import type { TriageItem } from '../api/types'
import { useProject } from '../app/project'
import { EVIDENCE_TABS, EvidenceTabs, type EvidenceTab } from '../features/triage/Evidence'
import { ReviewPanel } from '../features/triage/ReviewPanel'
import { MetricValue } from '../components/MetricValue'
import { Content, PageHeader } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { Badge, SeverityBadge, StatusBadge } from '../components/Status'
import { TrialStrip } from '../components/TrialStrip'
import { useKeyboardNav } from '../hooks/useKeyboardNav'

const BOOL_FILTERS: [string, string][] = [
  ['changed', 'Changed'],
  ['flaky', 'Flaky'],
  ['stable_wrong', 'Stable-wrong'],
  ['grading_error', 'Grading error'],
  ['provider_error', 'Provider error'],
]

const itemKey = (item: TriageItem) => `${item.case_id}:${item.candidate_key}`

function Flags({ item }: { item: TriageItem }) {
  const f = item.flags
  return (
    <span className="row" style={{ gap: 4 }}>
      {f.regression && <Badge tone="bad">regression</Badge>}
      {f.stable_wrong && <Badge tone="bad">stable-wrong</Badge>}
      {f.flaky && <Badge tone="warn">flaky</Badge>}
      {f.changed && <Badge tone="info">changed</Badge>}
      {f.grading_error && <Badge tone="warn">grading error</Badge>}
      {f.provider_error && <Badge tone="warn">provider error</Badge>}
      {f.invariant_failures.length > 0 && <Badge tone="bad">invariant</Badge>}
    </span>
  )
}

export function TriagePage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const runs = useRuns(projectId)
  const runId = params.get('run')
  const pane = params.get('pane') ?? 'queue'
  const tab = (EVIDENCE_TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as EvidenceTab) : 'overview'

  const set = (patch: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    setParams(next, { replace })
  }

  useEffect(() => {
    if (runId || !runs.data) return
    const first = runs.data.data.find((r) => r.status.startsWith('completed')) ?? runs.data.data[0]
    if (first) set({ run: first.id }, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, runs.data])

  const filters = {
    severity: params.get('severity') ?? undefined,
    candidate: params.get('cand') ?? undefined,
    review: params.get('review') ?? undefined,
    slice: params.get('slice') ?? undefined,
    ...Object.fromEntries(BOOL_FILTERS.filter(([k]) => params.get(k) === 'true').map(([k]) => [k, true])),
  }
  const triage = useTriage(runId, filters)
  const summary = useRunSummary(runId)
  const items = useMemo(() => triage.data?.items ?? [], [triage.data])
  const selectedIndex = Math.max(
    0,
    items.findIndex((i) => i.case_id === params.get('case') && (!params.get('candidate') || i.candidate_key === params.get('candidate'))),
  )
  const item = items[selectedIndex] ?? null
  const trialId = params.get('trial') ?? item?.representative_trial_id ?? item?.trials[0]?.id ?? null
  const trial = useTrial(trialId)
  const evidenceHeading = useRef<HTMLHeadingElement>(null)

  const select = (index: number) => {
    const next = items[index]
    if (next) set({ case: next.case_id, candidate: next.candidate_key, trial: null })
  }
  useKeyboardNav({
    next: () => select(Math.min(items.length - 1, selectedIndex + 1)),
    prev: () => select(Math.max(0, selectedIndex - 1)),
    open: () => {
      set({ pane: 'evidence' })
      evidenceHeading.current?.focus()
    },
    close: () => set({ pane: 'queue' }),
  })

  const run = runs.data?.data.find((r) => r.id === runId)
  const baselineKey = triage.data?.baseline
  const baselineCase = item && baselineKey && baselineKey !== item.candidate_key ? summary.data?.cases.find((c) => c.case_id === item.case_id)?.candidates[baselineKey] : null

  return (
    <>
      <PageHeader
        title="Triage"
        subtitle={run ? `${run.name || run.id.slice(0, 8)} · ${run.repeats ?? '?'} repeats per case` : 'Choose a run'}
        actions={
          runId && (
            <Link className="btn" to={`/runs/${runId}`}>
              Results
            </Link>
          )
        }
      />
      <Content>
        <div className="row" role="search" aria-label="Queue filters">
          <div className="field" style={{ width: 240 }}>
            <label htmlFor="triage-run">Run</label>
            <select id="triage-run" value={runId ?? ''} onChange={(e) => set({ run: e.target.value, case: null, candidate: null, trial: null })}>
              {(runs.data?.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name || r.id.slice(0, 8)} ({r.status.replace(/_/g, ' ')})
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 140 }}>
            <label htmlFor="triage-severity">Severity</label>
            <select id="triage-severity" value={params.get('severity') ?? ''} onChange={(e) => set({ severity: e.target.value })}>
              <option value="">Any</option>
              {['critical', 'high', 'medium', 'low'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 160 }}>
            <label htmlFor="triage-review">Review state</label>
            <select id="triage-review" value={params.get('review') ?? ''} onChange={(e) => set({ review: e.target.value })}>
              <option value="">Any</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="confirmed">Confirmed</option>
            </select>
          </div>
          <div className="field" style={{ width: 160 }}>
            <label htmlFor="triage-candidate">Candidate</label>
            <select id="triage-candidate" value={params.get('cand') ?? ''} onChange={(e) => set({ cand: e.target.value })}>
              <option value="">Any</option>
              {(triage.data?.candidates ?? []).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 180 }}>
            <label htmlFor="triage-slice">Slice (key=value)</label>
            <input id="triage-slice" value={params.get('slice') ?? ''} onChange={(e) => set({ slice: e.target.value }, true)} placeholder="language=en" />
          </div>
          <div className="row" role="group" aria-label="Flags" style={{ alignSelf: 'flex-end' }}>
            {BOOL_FILTERS.map(([key, label]) => (
              <button key={key} type="button" className="btn btn-sm" aria-pressed={params.get(key) === 'true'} onClick={() => set({ [key]: params.get(key) === 'true' ? null : 'true' })}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          {triage.data?.sort ? `Sorted by ${triage.data.sort}.` : ''} “Changed” means the candidate’s pass/fail pattern differs from the baseline on the same case.
          Keys: J / K move, Enter opens evidence, Esc returns to the queue.
        </p>

        <div className="tabs-list triage-tabs" role="tablist" aria-label="Triage panes">
          {['queue', 'evidence', 'review'].map((p) => (
            <button key={p} type="button" role="tab" aria-selected={pane === p} className="tab" onClick={() => set({ pane: p })}>
              {p[0]!.toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>

        {!runId && runs.isPending ? (
          <Loading />
        ) : !runId ? (
          <Empty title="No runs to triage" action={<Link className="btn" to="/runs/new">Set up a run</Link>} />
        ) : triage.isPending ? (
          <Loading />
        ) : triage.isError ? (
          <ErrorState error={triage.error} onRetry={() => void triage.refetch()} />
        ) : items.length === 0 ? (
          <Empty title="Nothing needs review">No case matches these filters. Clear filters or choose another run.</Empty>
        ) : (
          <div className="triage">
            <aside className="card triage-queue" data-pane="queue" data-active={pane === 'queue'} aria-label="Failure queue">
              <h4 style={{ marginBottom: 8 }}>Needs review · {items.length}</h4>
              <ul className="queue-list">
                {items.map((qi, index) => (
                  <li key={itemKey(qi)}>
                    <button
                      type="button"
                      className="queue-item"
                      aria-current={index === selectedIndex ? 'true' : undefined}
                      onClick={() => set({ case: qi.case_id, candidate: qi.candidate_key, trial: null, pane: 'evidence' })}
                      data-testid={`queue-${qi.external_id}`}
                    >
                      <span className="tiny muted">
                        {qi.external_id} · {qi.candidate_key} · {qi.priority_label}
                      </span>
                      <span className="queue-title" style={{ display: 'block' }}>
                        {qi.purpose.length > 70 ? `${qi.purpose.slice(0, 70)}…` : qi.purpose}
                      </span>
                      <span className="row small" style={{ gap: 6 }}>
                        <SeverityBadge severity={qi.severity} />
                        <span className="num">
                          {qi.counts.fails} of {qi.counts.trials} trials fail
                        </span>
                        {qi.review.state !== 'unreviewed' && <Badge tone="info">{qi.review.state.replace(/_/g, ' ')}</Badge>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>

            <section className="card" data-pane="evidence" data-active={pane === 'evidence'} aria-labelledby="evidence-title" style={{ minWidth: 0 }}>
              {item && (
                <div className="stack-lg">
                  <div className="row-between" style={{ alignItems: 'flex-start' }}>
                    <div className="stack" style={{ gap: 2 }}>
                      <h2 id="evidence-title" ref={evidenceHeading} tabIndex={-1}>
                        {item.external_id} · {item.candidate_key}
                      </h2>
                      <span className="small muted">{item.purpose}</span>
                      <Flags item={item} />
                    </div>
                    <span className={`badge ${item.flags.stable_wrong ? 'bad' : item.flags.flaky ? 'warn' : 'info'}`}>
                      {item.flags.stable_wrong ? 'Repeatable failure' : item.flags.flaky ? 'Observed flaky case' : item.priority_label}
                    </span>
                  </div>
                  <div className="grid grid-3">
                    <div>
                      <div className="kpi-label">Candidate task passes</div>
                      <MetricValue metric={item.pass_rate} runId={runId} size="big" label="Candidate task passes" />
                    </div>
                    <div>
                      <div className="kpi-label">Output agreement</div>
                      <MetricValue metric={item.agreement} runId={runId} size="big" label="Pairwise output agreement" />
                    </div>
                    <div>
                      <div className="kpi-label">Correctness prediction</div>
                      {typeof trial.data?.output?.probability === 'number' ? (
                        <span className="metric metric-big">
                          <span className="metric-value">{(trial.data.output.probability * 100).toFixed(1)}%</span>
                          <span className="metric-sub">raw score, not calibrated</span>
                        </span>
                      ) : (
                        <span className="metric metric-big" data-testid="prediction-unavailable">
                          <span className="metric-value metric-unavailable">Unavailable</span>
                          <span className="metric-sub">{trial.data?.output?.probability_unavailable_reason ?? 'No validated calibrator'}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="stack">
                    <h4>
                      {item.candidate_key} trials · ✓ pass / × fail
                    </h4>
                    <TrialStrip trials={item.trials} runId={runId} currentId={trialId} label={item.candidate_key} onSelect={(id) => set({ trial: id })} />
                    {baselineCase && baselineKey && (
                      <>
                        <h4>{baselineKey} trials</h4>
                        <TrialStrip trials={baselineCase.trials} runId={runId} label={baselineKey} onSelect={(id) => set({ trial: id })} />
                        <span className="small muted">
                          {baselineKey}: {baselineCase.counts.passes} / {baselineCase.counts.trials} pass · {item.candidate_key}: {item.counts.passes} / {item.counts.trials} pass
                        </span>
                      </>
                    )}
                  </div>
                  {trial.isPending ? (
                    <Loading />
                  ) : trial.isError ? (
                    <ErrorState error={trial.error} onRetry={() => void trial.refetch()} />
                  ) : (
                    <>
                      <p className="small">
                        Showing {trial.data.candidate_key} repeat {trial.data.repeat_index + 1}: <StatusBadge kind="trial" value={trial.data.status} />{' '}
                        <StatusBadge kind="outcome" value={trial.data.outcome} />
                        {trial.data.is_demo && <Badge tone="warn">demo fixture</Badge>}
                      </p>
                      <EvidenceTabs trial={trial.data} tab={tab} onTab={(t) => set({ tab: t === 'overview' ? null : t }, true)} />
                    </>
                  )}
                </div>
              )}
            </section>

            <aside className="card triage-review" data-pane="review" data-active={pane === 'review'} aria-label="Review">
              {trial.data ? <ReviewPanel key={trial.data.id} trial={trial.data} /> : <Loading lines={4} />}
            </aside>
          </div>
        )}
      </Content>
    </>
  )
}
