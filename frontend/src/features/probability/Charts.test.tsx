import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ReliabilityBin } from '../../api/types'
import { ReliabilityDiagram, RiskCoverage } from './Charts'

const bins: ReliabilityBin[] = Array.from({ length: 10 }, (_, i) => ({
  index: i,
  lower: i / 10,
  upper: (i + 1) / 10,
  count: i === 4 ? 0 : 3,
  positives: i === 4 ? 0 : 1,
  prediction: i === 4 ? null : i / 10 + 0.05,
  outcome: i === 4 ? null : 1 / 3,
  members: i === 4 ? [] : [`P${i}-0`, `P${i}-1`, `P${i}-2`],
}))

describe('chart table alternatives', () => {
  it('lists every bin, including empty ones, with counts', () => {
    render(<ReliabilityDiagram bins={bins} label="raw, test" selected={null} onSelect={() => undefined} />)
    const table = screen.getByTestId('reliability-table')
    expect(within(table).getAllByRole('row')).toHaveLength(11)
    expect(within(table).getByText('0 (empty)')).toBeInTheDocument()
    expect(within(table).getByText('0.4–0.5')).toBeInTheDocument()
  })

  it('opens a bin from the table without relying on hover', async () => {
    const onSelect = vi.fn()
    render(<ReliabilityDiagram bins={bins} label="raw" selected={null} onSelect={onSelect} />)
    await userEvent.click(screen.getAllByRole('button', { name: 'Open 3 cases' })[0]!)
    expect(onSelect).toHaveBeenCalledWith(0)
  })

  it('gives the risk–coverage curve a table with unavailable risk in words', () => {
    render(
      <RiskCoverage
        threshold={1}
        points={[
          { threshold: 0.5, accepted: 10, review: 5, total: 15, coverage: 2 / 3, risk: 0.2 },
          { threshold: 1, accepted: 0, review: 15, total: 15, coverage: 0, risk: null },
        ]}
      />,
    )
    const table = screen.getByTestId('risk-coverage-table')
    expect(within(table).getByText('Unavailable')).toBeInTheDocument()
    expect(within(table).getByText('20.0%')).toBeInTheDocument()
  })
})
