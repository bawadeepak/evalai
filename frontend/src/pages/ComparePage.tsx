// Compare: compatibility and exclusions first, then metric rows, then the
// Ready / Blocked / Inconclusive banner with exact reasons, and export.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, saveBlob } from '../api/client'
import { formatDate, formatNumber, formatPercent, formatSigned } from '../api/format'
import { useComparisons, useReleasePolicies, useRun, useRuns } from '../api/hooks'
import type { CaseChange, Comparison, ComparisonMetric } from '../api/types'
import { useProject } from '../app/project'
import { ActionError } from '../components/Misc'
import { Content, PageHeader, Section } from '../components/Page'
import { ErrorState, Loading } from '../components/States'
import { Badge, SeverityBadge, StatusBadge } from '../components/Status'
import { useToast } from '../components/Toast'

function sideValue(value: ComparisonMetric['baseline'], unit: string): string {
  if (value === null || value === undefined) return 'Unavailable'
  if (typeof value === 'number') return unit === 'fraction' ? formatPercent(value) : formatNumber(value)
  return `${value.passes} / ${value.graded} (${formatPercent(value.rate)})`
}

function CaseList({ title, items, baselineRun, candidateRun }: { title: string; items: CaseChange[]; baselineRun: string; candidateRun: string }) {
  if (items.length === 0) return null
  return (
    <details open={title !== 'Unchanged'}>
      <summary>
        <strong>{title}</strong> ({items.length})
      </summary>
      <div className="table-wrap" style={{ marginTop: 6 }}>
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Severity</th>
              <th>Cluster</th>
              <th className="num">Baseline</th>
              <th className="num">Candidate</th>
              <th className="num">Δ</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.external_id}>
                <td>{c.external_id}</td>
                <td>
                  <SeverityBadge severity={c.severity} />
                </td>
                <td className="small">{c.cluster}</td>
                <td className="num">{formatPercent(c.baseline)}</td>
                <td className="num">{formatPercent(c.candidate)}</td>
                <td className="num">{formatSigned(c.delta, 'fraction')}</td>
                <td className="small">
                  {c.baseline_trials[0] && <Link to={`/triage?run=${baselineRun}&trial=${c.baseline_trials[0]}`}>baseline</Link>}{' '}
                  {c.candidate_trials[0] && <Link to={`/triage?run=${candidateRun}&trial=${c.candidate_trials[0]}`}>candidate</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

export function ComparisonView({ comparison, baselineRun, candidateRun }: { comparison: Comparison; baselineRun: string; candidateRun: string }) {
  const { compatibility, decision } = comparison
  return (
    <div className="stack-lg" data-testid="comparison">
      <Section title="1. Compatibility and exclusions" id="compatibility">
        <p className="small">
          {compatibility.compatible ? <Badge tone="ok">✓ Compatible</Badge> : <Badge tone="bad">× Incompatible — inferential deltas disabled</Badge>} Paired{' '}
          {compatibility.paired_cases} of {compatibility.union_cases} cases ({formatPercent(compatibility.paired_coverage)}) on {comparison.pairing.method}.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Result</th>
                <th>Finding</th>
              </tr>
            </thead>
            <tbody>
              {compatibility.findings.map((f) => (
                <tr key={f.check}>
                  <td>{f.check.replace(/_/g, ' ')}</td>
                  <td>{f.ok ? <Badge tone="ok">✓ ok</Badge> : <Badge tone={f.blocks_inference ? 'bad' : 'warn'}>{f.blocks_inference ? '× blocks inference' : '! warning'}</Badge>}</td>
                  <td className="small">{f.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {comparison.exclusions.length > 0 ? (
          <ul className="small">
            {comparison.exclusions.map((e, i) => (
              <li key={i}>
                Excluded {e.external_id}
                {e.side ? ` (${e.side})` : ''}: {e.reason}
              </li>
            ))}
          </ul>
        ) : (
          <p className="small muted">No cases excluded.</p>
        )}
      </Section>
      <Section title="2. Metrics" id="metrics">
        <div className="table-wrap">
          <table data-testid="comparison-metrics">
            <thead>
              <tr>
                <th>Metric</th>
                <th className="num">Baseline</th>
                <th className="num">Candidate</th>
                <th className="num">Paired Δ</th>
                <th>Interval</th>
                <th>Units</th>
                <th className="num">Independent clusters</th>
                <th className="num">Margin</th>
                <th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {comparison.metrics.map((m) => (
                <tr key={m.name}>
                  <td>
                    {m.name.replace(/_/g, ' ')}
                    <div className="tiny muted">{m.definition}</div>
                  </td>
                  <td className="num">{sideValue(m.baseline, m.unit)}</td>
                  <td className="num">{sideValue(m.candidate, m.unit)}</td>
                  <td className="num">{m.inferential ? formatSigned(m.delta ?? null, m.unit) : '—'}</td>
                  <td className="small">
                    {m.inferential && m.lower !== null && m.lower !== undefined && m.upper !== null && m.upper !== undefined
                      ? `${formatSigned(m.lower, m.unit)} to ${formatSigned(m.upper, m.unit)} (${Math.round((m.confidence ?? 0.95) * 100)}% ${m.method?.replace(/_/g, ' ')}, ${m.resamples} resamples, seed ${m.seed})`
                      : m.inferential
                        ? `No interval${m.reason ? `: ${m.reason}` : ''}`
                        : 'Descriptive only'}
                    {m.warnings?.map((w) => (
                      <div key={w} className="tiny" style={{ color: 'var(--warning)' }}>
                        {w}
                      </div>
                    ))}
                  </td>
                  <td className="small">{m.unit}</td>
                  <td className="num">{m.independent_clusters ?? '—'}</td>
                  <td className="num">{m.margin === null || m.margin === undefined ? '—' : formatSigned(m.margin, m.unit).replace('+', '±')}</td>
                  <td>
                    <StatusBadge kind="gate" value={m.gate} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {comparison.metrics.map((m) => m.note).filter(Boolean)[0] && <p className="small muted">{comparison.metrics.map((m) => m.note).filter(Boolean)[0]}</p>}
        <div className="stack" style={{ marginTop: 10 }}>
          <CaseList title="Critical" items={comparison.case_changes.critical} baselineRun={baselineRun} candidateRun={candidateRun} />
          <CaseList title="Regressed" items={comparison.case_changes.regressed} baselineRun={baselineRun} candidateRun={candidateRun} />
          <CaseList title="Improved" items={comparison.case_changes.improved} baselineRun={baselineRun} candidateRun={candidateRun} />
          <CaseList title="Unresolved" items={comparison.case_changes.unresolved} baselineRun={baselineRun} candidateRun={candidateRun} />
          <CaseList title="Unchanged" items={comparison.case_changes.unchanged} baselineRun={baselineRun} candidateRun={candidateRun} />
        </div>
      </Section>
      <div className={`gate-banner ${decision.verdict}`} role="status" data-testid="gate-banner" data-verdict={decision.verdict}>
        <h2>
          <StatusBadge kind="gate" value={decision.verdict} /> {decision.verdict === 'ready' ? 'Ready' : decision.verdict === 'blocked' ? 'Blocked' : 'Inconclusive'}
          {decision.demo ? ' (demo data)' : ''}
        </h2>
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {decision.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
          {decision.reasons.length === 0 && <li>Every required check passed within its margin.</li>}
        </ul>
        {decision.multiplicity_note && <p className="small">{decision.multiplicity_note}</p>}
        <p className="small muted" style={{ margin: 0 }}>
          {decision.note}
        </p>
      </div>
    </div>
  )
}

export function ComparePage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const runs = useRuns(projectId)
  const policies = useReleasePolicies(projectId)
  const comparisons = useComparisons(projectId)
  const baselineRunId = params.get('baseline') ?? ''
  const candidateRunId = params.get('candidate') ?? ''
  const baselineRun = useRun(baselineRunId || null)
  const candidateRun = useRun(candidateRunId || null)
  const baselineKey = params.get('baseline_key') ?? baselineRun.data?.candidates[0]?.key ?? ''
  const candidateKey = params.get('candidate_key') ?? candidateRun.data?.candidates.at(-1)?.key ?? ''
  const policyId = params.get('policy') ?? policies.data?.[0]?.id ?? ''
  const [saved, setSaved] = useState<Comparison | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next, { replace: true })
    setSaved(null)
  }
  const body = { project_id: projectId, baseline_run_id: baselineRunId, baseline_key: baselineKey, candidate_run_id: candidateRunId, candidate_key: candidateKey, policy_id: policyId || null }
  const ready = !!(projectId && baselineRunId && candidateRunId && baselineKey && candidateKey)
  const preview = useQuery({
    queryKey: ['comparison-preview', body],
    queryFn: () => api.post<Comparison>('/comparisons/validate', body),
    enabled: ready,
    retry: false,
  })
  const save = useMutation({
    mutationFn: () => api.post<Comparison>('/comparisons', body),
    onSuccess: ({ data }) => {
      setSaved(data)
      void queryClient.invalidateQueries({ queryKey: ['comparisons'] })
      toast('Comparison saved with its manifest hashes.')
    },
  })
  async function exportEvidence(id: string) {
    const { data } = await api.get<unknown>(`/comparisons/${id}/export`)
    saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `comparison-${id.slice(0, 8)}.json`)
  }
  const runOptions = runs.data?.data ?? []
  const shown = saved ?? preview.data?.data ?? null

  return (
    <>
      <PageHeader
        title="Compare"
        subtitle="Paired by case identity; clustered paired bootstrap; an evidence gate, not a deployment action."
        actions={
          <>
            <button type="button" className="btn" disabled={!preview.data || save.isPending || !!saved} onClick={() => save.mutate()}>
              Save comparison
            </button>
            <button type="button" className="btn btn-primary" disabled={!saved?.id} onClick={() => saved?.id && void exportEvidence(saved.id)}>
              Export decision evidence
            </button>
          </>
        }
      />
      <Content>
        <Section title="Select runs" id="select">
          <div className="field-row">
            {(
              [
                ['baseline', 'Baseline run', baselineRunId, baselineRun.data?.candidates ?? [], 'baseline_key', baselineKey],
                ['candidate', 'Candidate run', candidateRunId, candidateRun.data?.candidates ?? [], 'candidate_key', candidateKey],
              ] as const
            ).map(([param, label, value, candidates, keyParam, keyValue]) => (
              <div key={param} className="stack">
                <div className="field">
                  <label htmlFor={`cmp-${param}`}>{label}</label>
                  <select id={`cmp-${param}`} value={value} onChange={(e) => set({ [param]: e.target.value, [keyParam]: null })}>
                    <option value="">Select a run…</option>
                    {runOptions.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name || r.id.slice(0, 8)} · {r.status.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor={`cmp-${param}-key`}>{label.replace('run', 'candidate')}</label>
                  <select id={`cmp-${param}-key`} value={keyValue} onChange={(e) => set({ [keyParam]: e.target.value })} disabled={!value}>
                    {candidates.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.key} — {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ))}
            <div className="field">
              <label htmlFor="cmp-policy">Release policy</label>
              <select id="cmp-policy" value={policyId} onChange={(e) => set({ policy: e.target.value })}>
                <option value="">Default policy</option>
                {(policies.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} v{p.version}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </Section>
        {!ready ? (
          <p className="muted">Choose a baseline and a candidate (runs and candidate keys).</p>
        ) : preview.isPending ? (
          <Loading />
        ) : preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : shown ? (
          <ComparisonView comparison={shown} baselineRun={baselineRunId} candidateRun={candidateRunId} />
        ) : null}
        <ActionError error={save.error} />
        <Section title="Saved comparisons" id="saved">
          {comparisons.isPending ? (
            <Loading lines={2} />
          ) : (comparisons.data ?? []).length === 0 ? (
            <p className="muted">None yet.</p>
          ) : (
            <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {comparisons.data!.map((c) => (
                <li key={c.id} className="row-between">
                  <span className="row">
                    <StatusBadge kind="gate" value={c.decision.verdict} />
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => set({ baseline: c.baseline_run_id ?? null, baseline_key: c.baseline_key ?? null, candidate: c.candidate_run_id ?? null, candidate_key: c.candidate_key ?? null, policy: c.policy_id ?? null })}
                    >
                      {c.baseline_key} → {c.candidate_key}
                    </button>
                    <span className="small muted">{formatDate(c.created_at)}</span>
                  </span>
                  <button type="button" className="btn btn-sm" onClick={() => c.id && void exportEvidence(c.id)}>
                    Export
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </Content>
    </>
  )
}
