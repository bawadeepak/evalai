import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { metric } from '../test/fixtures'
import { MetricValue } from './MetricValue'

const wrap = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('MetricValue', () => {
  it('renders an unavailable value with its reason instead of a number', () => {
    wrap(<MetricValue metric={metric({ value: null, unavailable_reason: 'k=5 exceeds graded repeats' })} />)
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('k=5 exceeds graded repeats')).toBeInTheDocument()
    expect(screen.queryByText(/0\.0%/)).not.toBeInTheDocument()
  })

  it('renders a missing metric object as unavailable, never zero', () => {
    wrap(<MetricValue metric={null} missingReason="no calibrator" />)
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('no calibrator')).toBeInTheDocument()
  })

  it('shows value, counts and the labelled interval', () => {
    wrap(<MetricValue metric={metric()} runId="run-1" />)
    expect(screen.getByText('90.0%')).toBeInTheDocument()
    expect(screen.getByText('18 / 20')).toBeInTheDocument()
    expect(screen.getByText('95% Wilson interval (frequentist): 69.9–97.2%')).toBeInTheDocument()
  })

  it('opens the definition and links every contributing trial', async () => {
    wrap(<MetricValue metric={metric()} runId="run-1" label="Candidate passes" />)
    await userEvent.click(screen.getByRole('button', { name: /Candidate passes: 90.0% \(18 \/ 20\)/ }))
    expect(screen.getByText('observed_pass_rate@1')).toBeInTheDocument()
    expect(screen.getByText('2 contributing trials')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 't-1' })).toHaveAttribute('href', '/triage?run=run-1&trial=t-1')
  })
})
