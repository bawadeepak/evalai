// One imported result file: upstream identity, the tool's own verdicts,
// assertions with provenance, scores (never probabilities) and errors.

import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatDate } from '../api/format'
import { useExternalImport } from '../api/hooks'
import type { ExternalResult } from '../api/types'
import { Json } from '../components/Content'
import { Hash, KeyValue } from '../components/Misc'
import { Content, PageHeader, Section } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { Badge, StatusBadge } from '../components/Status'

const PAGE = 200

function preview(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 110 ? `${text.slice(0, 110)}…` : text
}

function inputText(result: ExternalResult): unknown {
  const input = result.input
  return input.text ?? input.prompt ?? input.vars ?? input.messages ?? input
}

function ScoreList({ result }: { result: ExternalResult }) {
  if (result.scores.length === 0) return <span className="muted">—</span>
  return (
    <ul className="small" style={{ margin: 0, paddingLeft: 16 }}>
      {result.scores.map((s) => (
        <li key={s.name} title={s.definition}>
          {s.name}: <strong>{String(s.value)}</strong> <span className="muted">({s.kind}{s.note ? `, ${s.note}` : ''})</span>
        </li>
      ))}
    </ul>
  )
}

export function ExternalImportPage() {
  const { id } = useParams()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const query = useExternalImport(id, { status: status || undefined, limit: PAGE, offset })

  if (query.isPending)
    return (
      <>
        <PageHeader title="Imported results" />
        <Content>
          <Loading />
        </Content>
      </>
    )
  if (query.isError)
    return (
      <>
        <PageHeader title="Imported results" />
        <Content>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Content>
      </>
    )
  const row = query.data.data
  const total = Number(query.data.meta.total ?? 0)
  const summary = row.summary as Record<string, unknown>
  const results = row.results ?? []
  return (
    <>
      <PageHeader
        title={`${row.plugin === 'inspect' ? 'Inspect' : row.plugin === 'promptfoo' ? 'Promptfoo' : row.plugin} results`}
        subtitle={`${row.filename ?? 'imported file'} · imported ${formatDate(row.created_at)}`}
        actions={
          <Link className="btn" to="/settings#external">
            All imports
          </Link>
        }
      />
      <Content>
        <p className="notice info small">
          Verdicts and scores below are the upstream tool’s own. Eval Triage keeps them with their provenance; it does not re-grade them, and numeric
          scores are not probabilities.
        </p>
        <div className="kpis" data-testid="external-summary">
          {['results', 'pass', 'fail', 'error', 'unscored'].map((key) => (
            <div key={key} className="kpi">
              <div className="kpi-label">{key === 'results' ? 'Results' : `Upstream ${key}`}</div>
              <div className="metric-value num">{String(summary[key] ?? 0)}</div>
            </div>
          ))}
        </div>
        <div className="grid grid-2">
          <Section title="Source" id="source">
            <KeyValue
              items={[
                ['Plugin', `${row.plugin} (${row.plugin_version})`],
                ['Tool version', row.source_version ?? 'not recorded'],
                ...Object.entries(row.source_identity)
                  .filter(([, v]) => v !== null && v !== undefined && v !== '')
                  .map(([k, v]) => [k.replace(/_/g, ' '), typeof v === 'object' ? <code key={k} className="tiny">{JSON.stringify(v)}</code> : String(v)] as [string, React.ReactNode]),
                [
                  'Original file',
                  <span key="o" className="row">
                    <a href={`/api/v1/artifacts/${row.artifact_hash}`} target="_blank" rel="noreferrer">
                      open
                    </a>
                    <Hash value={row.artifact_hash} />
                    {summary.original_redacted ? <Badge tone="warn">stored redacted</Badge> : null}
                  </span>,
                ],
              ]}
            />
          </Section>
          <Section title="Notes" id="notes">
            {row.warnings.length === 0 ? <p className="small muted">No warnings.</p> : row.warnings.map((w) => <p key={w} className="notice warn small">{w}</p>)}
            {summary.run ? <Json value={summary.run} label="Run details" /> : null}
            {typeof summary.note === 'string' && <p className="small muted">{summary.note}</p>}
          </Section>
        </div>
        <Section
          title="Results"
          id="results"
          actions={
            <div className="field" style={{ width: 160 }}>
              <label htmlFor="external-status" className="sr-only">
                Filter by status
              </label>
              <select
                id="external-status"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">All statuses</option>
                {['pass', 'fail', 'error', 'unscored'].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          }
        >
          {results.length === 0 ? (
            <Empty title="No results match" />
          ) : (
            <div className="table-wrap">
              <table data-testid="external-results">
                <thead>
                  <tr>
                    <th className="sticky-col">Upstream id</th>
                    <th>Case</th>
                    <th>Status</th>
                    <th>Provider</th>
                    <th>Input</th>
                    <th>Output</th>
                    <th>Assertions</th>
                    <th>Scores (not probabilities)</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <Fragment key={r.id}>
                      <tr>
                        <td className="sticky-col">
                          <button type="button" className="link-button mono" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
                            {r.upstream_id}
                          </button>
                        </td>
                        <td className="small">{r.case_external_id ?? '—'}</td>
                        <td>
                          <StatusBadge kind="outcome" value={r.status} />
                        </td>
                        <td className="small">{r.provider ?? '—'}</td>
                        <td className="small">{preview(inputText(r))}</td>
                        <td className="small">{preview(r.output?.text ?? null)}</td>
                        <td className="small">
                          {r.assertions.length === 0 ? (
                            <span className="muted">—</span>
                          ) : (
                            <ul style={{ margin: 0, paddingLeft: 16 }}>
                              {r.assertions.map((a, i) => (
                                <li key={i}>
                                  <code>{a.type}</code> <Badge tone={a.status === 'pass' ? 'ok' : a.status === 'fail' ? 'bad' : 'warn'}>{a.status}</Badge>
                                  {a.reason && <div className="tiny muted">{a.reason}</div>}
                                </li>
                              ))}
                            </ul>
                          )}
                          {r.error && <div className="notice warn tiny">{String(r.error.message ?? 'error')}</div>}
                        </td>
                        <td>
                          <ScoreList result={r} />
                        </td>
                      </tr>
                      {open === r.id && (
                        <tr>
                          <td colSpan={8}>
                            <Json value={r} label={`Result ${r.upstream_id}`} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="row-between" style={{ marginTop: 10 }}>
            <span className="small muted">{total === 0 ? 'No results' : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`}</span>
            <div className="row">
              <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Previous
              </button>
              <button type="button" className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
                Next
              </button>
            </div>
          </div>
        </Section>
      </Content>
    </>
  )
}
