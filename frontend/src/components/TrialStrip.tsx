// One tile per repeat showing target status and grading outcome. Selecting a
// tile opens that trial's exact evidence.

import { Link } from 'react-router-dom'
import type { TrialStrip as Trial } from '../api/types'

const SYMBOL: Record<string, string> = { pass: '✓', fail: '×', unresolved: '?' }

export function tileClass(trial: Pick<Trial, 'outcome' | 'status' | 'grading_error'>): string {
  if (trial.outcome === 'pass') return 'tile pass'
  if (trial.outcome === 'fail') return 'tile fail'
  if (trial.outcome === 'unresolved' || trial.grading_error) return 'tile unresolved'
  return 'tile'
}

export function describeTrial(trial: Trial): string {
  const outcome = trial.outcome ?? 'not graded'
  const grading = trial.grading_error ? ', grading error' : ''
  return `Repeat ${trial.repeat + 1}: ${outcome} (target ${trial.status.replace(/_/g, ' ')}${grading})`
}

export function TrialStrip({
  trials,
  runId,
  currentId,
  label,
  onSelect,
}: {
  trials: Trial[]
  runId: string
  currentId?: string | null
  label?: string
  onSelect?: (id: string) => void
}) {
  const passes = trials.filter((t) => t.outcome === 'pass').length
  const fails = trials.filter((t) => t.outcome === 'fail').length
  const other = trials.length - passes - fails
  const summary = `${label ? `${label}: ` : ''}${passes} pass, ${fails} fail${other ? `, ${other} unresolved or pending` : ''}`
  return (
    <div className="strip" role="group" aria-label={summary}>
      {trials.map((trial) => {
        const symbol = SYMBOL[trial.outcome ?? ''] ?? (trial.status === 'pending' || trial.status === 'running' ? '·' : '–')
        const props = {
          className: tileClass(trial),
          title: describeTrial(trial),
          'aria-label': describeTrial(trial),
          'aria-current': currentId === trial.id ? ('true' as const) : undefined,
        }
        return onSelect ? (
          <button key={trial.id} type="button" {...props} onClick={() => onSelect(trial.id)}>
            {symbol}
          </button>
        ) : (
          <Link key={trial.id} to={`/triage?run=${runId}&trial=${trial.id}`} {...props}>
            {symbol}
          </Link>
        )
      })}
    </div>
  )
}

export function TileLegend() {
  return (
    <div className="tile-legend" aria-hidden="true">
      <span>
        <span className="tile pass">✓</span> pass
      </span>
      <span>
        <span className="tile fail">×</span> fail
      </span>
      <span>
        <span className="tile unresolved">?</span> unresolved / grading error
      </span>
      <span>
        <span className="tile">–</span> no output
      </span>
    </div>
  )
}
