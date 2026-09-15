// Evidence tabs for one trial: Overview, Output diff, Trace, Memory state,
// Grades, Attempts. Content is rendered as text or sanitised Markdown only.

import * as Tabs from '@radix-ui/react-tabs'
import { diffJson, diffWords } from 'diff'
import { useMemo, useState } from 'react'
import { formatDate, formatMs } from '../../api/format'
import { useTrial } from '../../api/hooks'
import type { MemoryFact, StoreState, TrialDetail } from '../../api/types'
import { readStorage, STORAGE_KEYS, writeStorage } from '../../app/storage'
import { Json, OutputText } from '../../components/Content'
import { KeyValue } from '../../components/Misc'
import { Loading, Unavailable } from '../../components/States'
import { Badge, StatusBadge } from '../../components/Status'

export const EVIDENCE_TABS = ['overview', 'diff', 'trace', 'memory', 'grades', 'attempts'] as const
export type EvidenceTab = (typeof EVIDENCE_TABS)[number]
const LABELS: Record<EvidenceTab, string> = {
  overview: 'Overview',
  diff: 'Output diff',
  trace: 'Trace',
  memory: 'Memory state',
  grades: 'Grades',
  attempts: 'Attempts',
}

function expectedText(expected: Record<string, unknown>): string {
  for (const key of ['label', 'answer', 'reference', 'text', 'output']) {
    const value = expected[key]
    if (typeof value === 'string') return value
  }
  return JSON.stringify(expected, null, 2)
}

function DiffView({ parts }: { parts: { value: string; added?: boolean; removed?: boolean }[] }) {
  return (
    <pre className="box" style={{ fontFamily: 'var(--mono)' }} aria-label="Differences: removed text is struck through, added text is highlighted">
      {parts.map((part, i) =>
        part.added ? (
          <ins key={i} className="diff-add">
            {part.value}
          </ins>
        ) : part.removed ? (
          <del key={i} className="diff-del">
            {part.value}
          </del>
        ) : (
          <span key={i}>{part.value}</span>
        ),
      )}
    </pre>
  )
}

function OutputDiff({ trial }: { trial: TrialDetail }) {
  const [against, setAgainst] = useState<string>('expected')
  const [mode, setMode] = useState<'raw' | 'json'>('raw')
  const other = useTrial(against !== 'expected' ? against : null)
  const mine = trial.output?.text ?? ''
  let left: { text: string; parsed: unknown; parseError: string | null; label: string }
  if (against === 'expected') {
    left = { text: expectedText(trial.case.expected), parsed: trial.case.expected, parseError: null, label: 'Expected' }
  } else if (other.data) {
    left = {
      text: other.data.output?.text ?? '',
      parsed: other.data.output?.parsed ?? null,
      parseError: other.data.output?.parse_error ?? null,
      label: `${other.data.candidate_key} repeat ${other.data.repeat_index + 1}`,
    }
  } else {
    left = { text: '', parsed: null, parseError: null, label: 'Loading…' }
  }
  const myParsed = trial.output?.parsed ?? null
  const parts = useMemo(() => {
    if (mode === 'json') {
      if (myParsed === null || left.parsed === null) return null
      return diffJson(left.parsed as object, myParsed as object)
    }
    return diffWords(left.text, mine)
  }, [mode, left.parsed, left.text, mine, myParsed])
  return (
    <div className="stack-lg">
      <div className="row">
        <div className="field" style={{ width: 280 }}>
          <label htmlFor="diff-against">Compare this output against</label>
          <select id="diff-against" value={against} onChange={(e) => setAgainst(e.target.value)}>
            <option value="expected">Expected contract</option>
            {trial.siblings
              .filter((s) => s.id !== trial.id)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.candidate_key} repeat {s.repeat_index + 1} ({s.status.replace(/_/g, ' ')})
                </option>
              ))}
          </select>
        </div>
        <div className="row" role="group" aria-label="Diff mode">
          <button type="button" className="btn btn-sm" aria-pressed={mode === 'raw'} onClick={() => setMode('raw')}>
            Raw text
          </button>
          <button type="button" className="btn btn-sm" aria-pressed={mode === 'json'} onClick={() => setMode('json')}>
            Parsed JSON
          </button>
        </div>
      </div>
      {against !== 'expected' && other.isPending ? (
        <Loading lines={2} />
      ) : parts === null ? (
        <div className="stack">
          <p className="notice warn small">
            No parsed JSON on {myParsed === null ? 'this trial' : left.label}
            {trial.output?.parse_error ? `: ${trial.output.parse_error}` : left.parseError ? `: ${left.parseError}` : ''}. Showing raw text.
          </p>
          <DiffView parts={diffWords(left.text, mine)} />
        </div>
      ) : (
        <>
          <p className="small muted">
            Struck-through text appears only in “{left.label}”; highlighted text appears only in this trial.
          </p>
          <DiffView parts={parts} />
        </>
      )}
    </div>
  )
}

function Trace({ trial }: { trial: TrialDetail }) {
  const [open, setOpen] = useState<string | null>(null)
  const output = trial.output
  return (
    <div className="stack-lg">
      {trial.steps.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Step</th>
                <th>Action</th>
                <th>Store</th>
                <th>Status</th>
                <th className="num">Elapsed</th>
                <th>New events</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {trial.steps.map((step) => (
                <tr key={step.step_id}>
                  <td>
                    <button type="button" className="link-button" aria-expanded={open === step.step_id} onClick={() => setOpen(open === step.step_id ? null : step.step_id)}>
                      {step.step_id}
                    </button>
                    {open === step.step_id && (
                      <div style={{ marginTop: 6, minWidth: 320 }}>
                        <Json value={step.output} label={`Step ${step.step_id} output`} />
                      </div>
                    )}
                  </td>
                  <td>{step.action}</td>
                  <td>{step.store}</td>
                  <td>
                    <Badge tone={step.status === 'ok' ? 'ok' : step.status === 'skipped' ? 'na' : 'warn'}>{step.status}</Badge>
                  </td>
                  <td className="num">{formatMs(step.elapsed_ms)}</td>
                  <td className="small">{step.new_event_ids.join(', ') || '—'}</td>
                  <td className="small">{step.skip_reason ?? (step.error ? String(step.error.message ?? step.error.code ?? 'error') : '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">Single-call trial: no episode steps.</p>
      )}
      {(output?.tool_calls?.length ?? 0) > 0 && (
        <div className="stack">
          <h3>Tool calls</h3>
          <Json value={output?.tool_calls} />
        </div>
      )}
      {(output?.effects?.length ?? 0) > 0 && (
        <div className="stack">
          <h3>Effects</h3>
          <Json value={output?.effects} />
        </div>
      )}
      {output?.retrieved_ids && (
        <div className="stack">
          <h3>Retrieved evidence</h3>
          <p className="small">{output.retrieved_ids.join(', ') || 'none'}</p>
        </div>
      )}
      <div className="stack">
        <h3>Usage by attempt</h3>
        <ul className="small">
          {trial.attempts.map((a) => (
            <li key={a.id}>
              {a.stage} #{a.attempt_index + 1}: {formatMs(a.latency_ms)} · usage {JSON.stringify(a.usage)} · cost{' '}
              {Object.keys(a.cost).length ? JSON.stringify(a.cost) : 'unknown'}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

type Snapshot = { label: string; store: string; state: StoreState }

export function snapshotsOf(trial: TrialDetail): Snapshot[] {
  const snaps: Snapshot[] = []
  for (const step of trial.steps) {
    if (step.action === 'inspect_state' && step.output && Array.isArray((step.output as StoreState).facts)) {
      snaps.push({ label: `after step ${step.step_id}`, store: step.store, state: step.output as StoreState })
    }
  }
  for (const [store, state] of Object.entries(trial.output?.stores ?? {})) snaps.push({ label: `final (${store})`, store, state })
  return snaps
}

export function factDiff(before: MemoryFact[], after: MemoryFact[]) {
  const key = (f: MemoryFact) => f.claim
  const a = new Map(before.map((f) => [key(f), f]))
  const b = new Map(after.map((f) => [key(f), f]))
  return {
    added: after.filter((f) => !a.has(key(f))),
    removed: before.filter((f) => !b.has(key(f))),
    changed: after.filter((f) => a.has(key(f)) && a.get(key(f))!.state !== f.state).map((f) => ({ fact: f, from: a.get(key(f))!.state })),
  }
}

const STATE_TONE: Record<string, 'ok' | 'warn' | 'bad' | 'na'> = { active: 'ok', historical: 'na', rejected: 'bad', invalidated: 'warn', retracted: 'warn', pending: 'warn' }

function MemoryState({ trial }: { trial: TrialDetail }) {
  const snaps = snapshotsOf(trial)
  const [a, setA] = useState(0)
  const [b, setB] = useState(Math.max(0, snaps.length - 1))
  if (snaps.length === 0) return <Unavailable title="No memory state" reason="This trial is not a memory episode, so there is no store state to inspect." />
  const before = snaps[a]!
  const after = snaps[b]!
  const diff = factDiff(before.state.facts, after.state.facts)
  return (
    <div className="stack-lg">
      <div className="row">
        {[
          ['state-a', 'Before', a, setA],
          ['state-b', 'After', b, setB],
        ].map(([id, label, value, set]) => (
          <div className="field" style={{ width: 240 }} key={id as string}>
            <label htmlFor={id as string}>{label as string}</label>
            <select id={id as string} value={value as number} onChange={(e) => (set as (n: number) => void)(Number(e.target.value))}>
              {snaps.map((s, i) => (
                <option key={i} value={i}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <p className="small">
        {diff.added.length} added · {diff.removed.length} no longer present · {diff.changed.length} changed state
      </p>
      {(diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0) && (
        <ul className="small">
          {diff.added.map((f) => (
            <li key={`a-${f.claim}`}>
              <ins className="diff-add">+ {f.claim}</ins> ({f.state})
            </li>
          ))}
          {diff.removed.map((f) => (
            <li key={`r-${f.claim}`}>
              <del className="diff-del">− {f.claim}</del>
            </li>
          ))}
          {diff.changed.map(({ fact, from }) => (
            <li key={`c-${fact.claim}`}>
              {fact.claim}: {from} → {fact.state}
            </li>
          ))}
        </ul>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Claim ({after.label})</th>
              <th>State</th>
              <th>Source step</th>
              <th>Memory id</th>
            </tr>
          </thead>
          <tbody>
            {after.state.facts.map((f, i) => (
              <tr key={`${f.claim}-${i}`}>
                <td>{f.claim}</td>
                <td>
                  <Badge tone={STATE_TONE[f.state] ?? 'na'}>{f.state}</Badge>
                </td>
                <td className="small">{f.source_step ?? '—'}</td>
                <td className="small mono">{f.memory_id ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <KeyValue
        items={[
          ['Backend', after.state.backend],
          ['Exhaustive', after.state.exhaustive ? 'yes — every stored fact was paged' : 'no — this snapshot may be incomplete'],
          ['Truncated in MemoryAI state()', after.state.truncated_in_memoryai_state ? 'yes (MemoryAI lists at most 200)' : 'no'],
          ['Counts', JSON.stringify(after.state.counts ?? {})],
        ]}
      />
      {(after.state.notes ?? []).map((n) => (
        <p key={n} className="small muted">
          {n}
        </p>
      ))}
    </div>
  )
}

function Grades({ trial }: { trial: TrialDetail }) {
  if (trial.grades.length === 0) return <Unavailable title="Not graded" reason="No grades are stored for this trial yet." />
  return (
    <div className="stack-lg">
      {trial.outcomes.map((o) => (
        <p key={o.grading_run_id} className="small">
          Outcome <StatusBadge kind="outcome" value={o.outcome} /> {o.reason}
        </p>
      ))}
      {trial.grades.map((g) => (
        <article key={g.id} className="card stack" data-testid="grade">
          <div className="row-between">
            <strong>
              {g.grader_name} <span className="muted small">({g.grader_kind}, v{g.grader_version})</span>
            </strong>
            <StatusBadge kind="outcome" value={g.verdict} />
          </div>
          {g.explanation && <p className="small">{g.explanation}</p>}
          {g.reason && <p className="small muted">{g.reason}</p>}
          {g.error && <p className="notice warn small">Grading error: {String(g.error.message ?? g.error.code)}</p>}
          {g.checks.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {g.checks.map((c) => (
                    <tr key={c.name}>
                      <td>{c.name}</td>
                      <td>
                        <Badge tone={c.status === 'pass' ? 'ok' : c.status === 'fail' ? 'bad' : c.status === 'not_applicable' ? 'na' : 'warn'}>{c.status.replace(/_/g, ' ')}</Badge>
                      </td>
                      <td className="small">
                        {c.detail}
                        {c.evidence.length > 0 && (
                          <details>
                            <summary>Evidence</summary>
                            <Json value={c.evidence} />
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {g.evidence_refs.length > 0 && <Json value={g.evidence_refs} label="Judge evidence" />}
          {g.judge_attempts.length > 0 && (
            <details>
              <summary className="small">
                Judge attempts ({g.judge_attempts.length}) — every attempt is kept
              </summary>
              <Json value={g.judge_attempts} />
            </details>
          )}
        </article>
      ))}
    </div>
  )
}

function Attempts({ trial }: { trial: TrialDetail }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Stage</th>
            <th>#</th>
            <th>Status</th>
            <th>Model</th>
            <th className="num">Latency</th>
            <th>Retry reason</th>
            <th>Mutation outcome</th>
            <th>Artifacts</th>
          </tr>
        </thead>
        <tbody>
          {trial.attempts.map((a) => (
            <tr key={a.id} className={a.id === trial.selected_attempt_id ? 'selected' : undefined}>
              <td>{a.stage}</td>
              <td className="num">{a.attempt_index + 1}</td>
              <td>
                <StatusBadge kind="trial" value={a.status} />
                {a.error && <div className="tiny">{String(a.error.message ?? a.error.code ?? '')}</div>}
              </td>
              <td className="small">
                {a.requested_model ?? '—'}
                {a.actual_model && a.actual_model !== a.requested_model ? ` → ${a.actual_model}` : ''}
              </td>
              <td className="num">{formatMs(a.latency_ms)}</td>
              <td className="small">{a.retry_reason ?? '—'}</td>
              <td className="small">
                {a.mutation_outcome_known === false ? <Badge tone="warn">? unknown — may have been applied</Badge> : a.mutation_outcome_known ? 'known' : '—'}
              </td>
              <td className="small">
                {a.request_artifact && (
                  <a href={`/api/v1/artifacts/${a.request_artifact}`} target="_blank" rel="noreferrer">
                    request
                  </a>
                )}{' '}
                {a.response_artifact && (
                  <a href={`/api/v1/artifacts/${a.response_artifact}`} target="_blank" rel="noreferrer">
                    response
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted" style={{ padding: 8 }}>
        Started {formatDate(trial.started_at)} · finished {formatDate(trial.finished_at)}. The highlighted attempt produced the stored output.
      </p>
    </div>
  )
}

function Overview({ trial }: { trial: TrialDetail }) {
  const [markdown, setMarkdown] = useState(() => readStorage(STORAGE_KEYS.markdown) === '1')
  const c = trial.case
  return (
    <div className="stack-lg">
      <div className="stack">
        <h4>Input</h4>
        {c.episode.length ? (
          <ol className="small" style={{ margin: 0 }}>
            {c.episode.map((step) => (
              <li key={step.id}>
                <code>{step.id}</code> {step.action}
                {typeof step.args.text === 'string' ? `: “${step.args.text}”` : typeof step.args.query === 'string' ? `: “${step.args.query}”` : ''}
              </li>
            ))}
          </ol>
        ) : typeof c.input.text === 'string' ? (
          <div className="box input">{c.input.text}</div>
        ) : (
          <Json value={c.input} />
        )}
      </div>
      <div className="pair">
        <div className="stack">
          <h4>Expected contract</h4>
          <Json value={c.expected} label="Expected" />
          {c.alternatives.length > 0 && <p className="small">Allowed alternatives: {JSON.stringify(c.alternatives)}</p>}
        </div>
        <div className="stack">
          <div className="row-between">
            <h4>Actual output</h4>
            <label className="checkbox tiny">
              <input
                type="checkbox"
                checked={markdown}
                onChange={(e) => {
                  setMarkdown(e.target.checked)
                  writeStorage(STORAGE_KEYS.markdown, e.target.checked ? '1' : null)
                }}
              />
              Render Markdown
            </label>
          </div>
          <div className={`box${trial.outcome === 'fail' ? ' fail' : ''}`}>
            <OutputText text={trial.output?.text} markdown={markdown} />
          </div>
          {trial.output?.parse_error && <p className="notice warn small">Parse error: {trial.output.parse_error}</p>}
          {trial.output?.parsed !== null && trial.output?.parsed !== undefined && <Json value={trial.output.parsed} label="Parsed output" />}
        </div>
      </div>
      <KeyValue
        items={[
          ['Outcome', <span key="o" className="row"><StatusBadge kind="outcome" value={trial.outcome} /> <span className="small">{trial.outcome_reason}</span></span>],
          ['Target status', <StatusBadge key="t" kind="trial" value={trial.status} />],
          ['Error', trial.error_code ?? '—'],
          ['Invariant failures', trial.invariant_failures.join(', ') || 'none'],
          ['Cluster', trial.cluster_id],
          ['Scenario', `${trial.scenario_contract.name} v${trial.scenario_contract.version}`],
        ]}
      />
      {c.evidence.length > 0 && (
        <div className="stack">
          <h4>Source references</h4>
          <Json value={c.evidence} />
        </div>
      )}
      <p className="small">
        Stored artifacts:{' '}
        {[...trial.output_artifacts, ...trial.state_artifacts].map((h) => (
          <a key={h} href={`/api/v1/artifacts/${h}`} target="_blank" rel="noreferrer" className="mono" style={{ marginRight: 8 }}>
            {h.slice(0, 10)}
          </a>
        ))}
      </p>
    </div>
  )
}

export function EvidenceTabs({ trial, tab, onTab }: { trial: TrialDetail; tab: EvidenceTab; onTab: (tab: EvidenceTab) => void }) {
  return (
    <Tabs.Root value={tab} onValueChange={(v) => onTab(v as EvidenceTab)}>
      <Tabs.List className="tabs-list" aria-label="Evidence">
        {EVIDENCE_TABS.map((t) => (
          <Tabs.Trigger key={t} value={t} className="tab">
            {LABELS[t]}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      <Tabs.Content value="overview" className="tab-panel">
        <Overview trial={trial} />
      </Tabs.Content>
      <Tabs.Content value="diff" className="tab-panel">
        <OutputDiff trial={trial} />
      </Tabs.Content>
      <Tabs.Content value="trace" className="tab-panel">
        <Trace trial={trial} />
      </Tabs.Content>
      <Tabs.Content value="memory" className="tab-panel">
        <MemoryState trial={trial} />
      </Tabs.Content>
      <Tabs.Content value="grades" className="tab-panel">
        <Grades trial={trial} />
      </Tabs.Content>
      <Tabs.Content value="attempts" className="tab-panel">
        <Attempts trial={trial} />
      </Tabs.Content>
    </Tabs.Root>
  )
}
