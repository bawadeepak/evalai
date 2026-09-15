// The single renderer for every number in the UI. It shows the value with its
// unit, the counts it came from, the uncertainty with its method label, or the
// reason it is unavailable — and it opens the contributing trials.

import * as Popover from '@radix-ui/react-popover'
import { Link } from 'react-router-dom'
import { formatInterval, formatNumber, formatValue, humanize } from '../api/format'
import type { MetricValue as Metric } from '../api/types'

type Props = {
  metric: Metric | null | undefined
  label?: string
  runId?: string
  size?: 'normal' | 'big'
  showCounts?: boolean
  showInterval?: boolean
  /** Fallback text when no metric object exists at all. */
  missingReason?: string
}

const MAX_LINKS = 60

export function MetricValue({ metric, label, runId, size = 'normal', showCounts = true, showInterval = true, missingReason }: Props) {
  const className = `metric${size === 'big' ? ' metric-big' : ''}`
  if (!metric || metric.value === null || metric.value === undefined) {
    const reason = metric?.unavailable_reason ?? missingReason ?? 'not computed for this selection'
    return (
      <span className={className} data-testid={metric ? `metric-${metric.name}` : 'metric-missing'}>
        <span className="metric-value metric-unavailable">Unavailable</span>
        <span className="metric-sub">{reason}</span>
      </span>
    )
  }
  const text = formatValue(metric.value, metric.unit)
  const interval = showInterval ? formatInterval(metric.uncertainty, metric.unit) : null
  const counts =
    showCounts && metric.numerator !== null && metric.denominator !== null
      ? `${formatNumber(metric.numerator)} / ${formatNumber(metric.denominator)}`
      : null
  const trials = metric.contributing_trial_ids ?? []
  return (
    <span className={className} data-testid={`metric-${metric.name}`}>
      <Popover.Root>
        <Popover.Trigger asChild>
          <button
            type="button"
            className="metric-trigger"
            aria-label={`${label ?? humanize(metric.name)}: ${text}${counts ? ` (${counts})` : ''}. Show definition and evidence`}
          >
            <span className="metric-value">{text}</span>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className="popover" sideOffset={6} align="start">
            <strong>{label ?? humanize(metric.name)}</strong>
            <dl>
              <dt>Value</dt>
              <dd>{text}</dd>
              {counts && (
                <>
                  <dt>Counts</dt>
                  <dd>{counts}</dd>
                </>
              )}
              <dt>Unit</dt>
              <dd>{metric.unit}</dd>
              <dt>Direction</dt>
              <dd>{humanize(metric.direction)}</dd>
              <dt>Definition</dt>
              <dd className="mono">{metric.definition_version}</dd>
              {typeof metric.provenance?.formula === 'string' && (
                <>
                  <dt>Formula</dt>
                  <dd className="mono">{metric.provenance.formula}</dd>
                </>
              )}
              <dt>Eligible</dt>
              <dd>{metric.eligible_count ?? '—'}</dd>
              <dt>Missing</dt>
              <dd>{metric.missing_count ?? '—'}</dd>
              {metric.uncertainty && (
                <>
                  <dt>Uncertainty</dt>
                  <dd>
                    {metric.uncertainty.label}
                    {interval ? `: ${interval}` : ''}
                    {metric.uncertainty.note ? ` — ${metric.uncertainty.note}` : ''}
                  </dd>
                </>
              )}
            </dl>
            <div className="stack">
              <span className="muted">
                {trials.length} contributing trial{trials.length === 1 ? '' : 's'}
                {metric.contributing_case_ids?.length ? ` · ${metric.contributing_case_ids.length} cases` : ''}
              </span>
              {runId && trials.length > 0 && (
                <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0, gap: 2 }}>
                  {trials.slice(0, MAX_LINKS).map((id) => (
                    <li key={id}>
                      <Link to={`/triage?run=${runId}&trial=${id}`} className="mono">
                        {id.slice(0, 8)}
                      </Link>
                    </li>
                  ))}
                  {trials.length > MAX_LINKS && <li className="muted">…and {trials.length - MAX_LINKS} more</li>}
                </ul>
              )}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {counts && <span className="metric-sub num">{counts}</span>}
      {interval && metric.uncertainty && (
        <span className="metric-sub">
          {metric.uncertainty.label}: {interval}
        </span>
      )}
    </span>
  )
}
