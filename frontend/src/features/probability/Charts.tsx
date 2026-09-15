// Reliability diagram and risk–coverage curve. Each chart has an accessible
// table with the same numbers; nothing depends on hover.

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { formatPercent } from '../../api/format'
import type { ReliabilityBin, Selective } from '../../api/types'

export function ReliabilityDiagram({
  bins,
  label,
  selected,
  onSelect,
}: {
  bins: ReliabilityBin[]
  label: string
  selected: number | null
  onSelect: (index: number) => void
}) {
  const points = bins.filter((b) => b.count > 0 && b.prediction !== null && b.outcome !== null).map((b) => ({ x: b.prediction, y: b.outcome, count: b.count, index: b.index }))
  return (
    <figure className="stack" style={{ margin: 0 }} aria-label={`Reliability diagram (${label})`}>
      <div className="chart-box" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <CartesianGrid stroke="var(--line)" />
            <XAxis type="number" dataKey="x" domain={[0, 1]} name="Predicted probability" label={{ value: 'Predicted probability', position: 'bottom', fill: 'var(--muted)' }} tick={{ fill: 'var(--muted)' }} />
            <YAxis type="number" dataKey="y" domain={[0, 1]} name="Observed positive rate" label={{ value: 'Observed rate', angle: -90, position: 'insideLeft', fill: 'var(--muted)' }} tick={{ fill: 'var(--muted)' }} />
            <ZAxis type="number" dataKey="count" range={[50, 500]} name="Count" />
            <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--muted)" strokeDasharray="4 4" />
            <Tooltip cursor={false} />
            <Scatter
              data={points}
              fill="var(--accent)"
              onClick={(entry: unknown) => {
                const index = (entry as { payload?: { index?: number }; index?: number })?.payload?.index ?? (entry as { index?: number })?.index
                if (typeof index === 'number') onSelect(index)
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="small muted">
        Dashed line: perfect calibration. Point size shows the number of predictions in the bin. Empty bins are listed in the table.
      </figcaption>
      <div className="table-wrap">
        <table data-testid="reliability-table">
          <caption className="sr-only">Reliability bins ({label})</caption>
          <thead>
            <tr>
              <th>Bin</th>
              <th className="num">Count</th>
              <th className="num">Positives</th>
              <th className="num">Mean predicted</th>
              <th className="num">Observed rate</th>
              <th>
                <span className="sr-only">Cases</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {bins.map((b) => (
              <tr key={b.index} className={selected === b.index ? 'selected' : undefined}>
                <td className="nowrap">
                  {b.lower.toFixed(1)}–{b.upper.toFixed(1)}
                </td>
                <td className="num">{b.count === 0 ? '0 (empty)' : b.count}</td>
                <td className="num">{b.count ? b.positives : '—'}</td>
                <td className="num">{b.prediction === null ? '—' : formatPercent(b.prediction)}</td>
                <td className="num">{b.outcome === null ? '—' : formatPercent(b.outcome)}</td>
                <td>
                  {b.count > 0 && (
                    <button type="button" className="btn btn-sm" onClick={() => onSelect(b.index)} aria-pressed={selected === b.index}>
                      Open {b.count} case{b.count === 1 ? '' : 's'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}

export function RiskCoverage({ points, threshold }: { points: Selective[]; threshold: number }) {
  const data = points.filter((p) => p.risk !== null).map((p) => ({ coverage: p.coverage, risk: p.risk, threshold: p.threshold }))
  return (
    <figure className="stack" style={{ margin: 0 }} aria-label="Risk–coverage curve">
      <div className="chart-box" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <CartesianGrid stroke="var(--line)" />
            <XAxis type="number" dataKey="coverage" domain={[0, 1]} label={{ value: 'Coverage (accepted share)', position: 'bottom', fill: 'var(--muted)' }} tick={{ fill: 'var(--muted)' }} />
            <YAxis type="number" domain={[0, 1]} label={{ value: 'Selective risk', angle: -90, position: 'insideLeft', fill: 'var(--muted)' }} tick={{ fill: 'var(--muted)' }} />
            <Tooltip />
            <Line type="stepAfter" dataKey="risk" stroke="var(--accent)" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details>
        <summary className="small">Table of thresholds (current threshold {threshold.toFixed(2)})</summary>
        <div className="table-wrap">
          <table data-testid="risk-coverage-table">
            <thead>
              <tr>
                <th className="num">Threshold</th>
                <th className="num">Accepted</th>
                <th className="num">Sent to review</th>
                <th className="num">Coverage</th>
                <th className="num">Risk</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.threshold} className={Math.abs(p.threshold - threshold) < 1e-9 ? 'selected' : undefined}>
                  <td className="num">{p.threshold.toFixed(2)}</td>
                  <td className="num">{p.accepted}</td>
                  <td className="num">{p.review}</td>
                  <td className="num">{formatPercent(p.coverage)}</td>
                  <td className="num">{p.risk === null ? 'Unavailable' : formatPercent(p.risk)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
