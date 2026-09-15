import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderWithProviders, stubApi } from '../../test/render'
import { trialDetail } from '../../test/fixtures'
import { currentReviews, ReviewPanel, validateReview } from './ReviewPanel'

describe('review validation', () => {
  it('requires a reason for ambiguous and grader-incorrect decisions only', () => {
    expect(validateReview('ambiguous', '', 'Ana').reason).toBeTruthy()
    expect(validateReview('grader_incorrect', '  ', 'Ana').reason).toBeTruthy()
    expect(validateReview('confirm_failure', '', 'Ana')).toEqual({})
    expect(validateReview('acceptable_variation', '', 'Ana')).toEqual({})
  })

  it('requires a reviewer and a decision', () => {
    expect(validateReview(null, '', '')).toMatchObject({ decision: expect.any(String), reviewer: expect.any(String) })
  })

  it('treats superseded reviews as history', () => {
    const base = { trial_id: 't', reviewer: 'a', explanation: '', evidence_refs: [], grade_ids: [], superseded_by: null, links: {}, created_at: '' }
    const reviews = [
      { ...base, id: 'r1', decision: 'confirm_failure' as const, supersedes_id: null },
      { ...base, id: 'r2', decision: 'acceptable_variation' as const, supersedes_id: 'r1' },
    ]
    expect(currentReviews(reviews).map((r) => r.id)).toEqual(['r2'])
  })
})

describe('ReviewPanel', () => {
  it('blocks a grader-incorrect review without a reason and sends nothing', async () => {
    const { calls } = stubApi({
      'GET /api/v1/reviews': () => [],
      'GET /api/v1/projects': () => [],
      'GET /api/v1/trials/trial-1/adjudicated': () => ({ trial_id: 'trial-1', machine_outcome: 'fail', machine_provenance: [], human_review: null, adjudicated_outcome: 'fail', adjudication_source: 'machine grades', disagreement: false, note: '' }),
    })
    renderWithProviders(<ReviewPanel trial={trialDetail()} />)
    await userEvent.type(screen.getByLabelText('Reviewer name'), 'Ana')
    await userEvent.click(screen.getByRole('radio', { name: 'Grader incorrect' }))
    await userEvent.click(screen.getByRole('button', { name: 'Record review' }))
    expect(await screen.findByText('A reason is required for this decision')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('records a confirm-failure review with the reviewer name', async () => {
    const { calls } = stubApi({
      'GET /api/v1/reviews': () => [],
      'GET /api/v1/projects': () => [],
      'GET /api/v1/trials/trial-1/adjudicated': () => ({ trial_id: 'trial-1', machine_outcome: 'fail', machine_provenance: [], human_review: null, adjudicated_outcome: 'fail', adjudication_source: 'machine grades', disagreement: false, note: '' }),
      'POST /api/v1/reviews': () => ({ id: 'r1', trial_id: 'trial-1', decision: 'confirm_failure', reviewer: 'Ana', explanation: '', evidence_refs: [], grade_ids: [], supersedes_id: null, superseded_by: null, links: {}, created_at: '' }),
    })
    renderWithProviders(<ReviewPanel trial={trialDetail()} />)
    await userEvent.type(screen.getByLabelText('Reviewer name'), 'Ana')
    await userEvent.click(screen.getByRole('radio', { name: 'Confirm failure' }))
    await userEvent.click(screen.getByRole('button', { name: 'Record review' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.body).toMatchObject({ trial_id: 'trial-1', decision: 'confirm_failure', reviewer: 'Ana' })
  })
})
