// Human review: append-only decisions (optionally superseding the latest),
// the adjudicated view with provenance, more trials, and regression promotion
// with an explicit expected contract. Reviews never overwrite machine grades.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, newIdempotencyKey } from '../../api/client'
import { formatDate } from '../../api/format'
import { useAdjudicated, useDatasets, useReviews } from '../../api/hooks'
import type { Dataset, Review, ReviewDecision, TrialDetail } from '../../api/types'
import { useProject } from '../../app/project'
import { getReviewer, setReviewer } from '../../app/storage'
import { ActionError } from '../../components/Misc'
import { Field, parseJsonObject } from '../../components/Page'
import { Badge, StatusBadge } from '../../components/Status'
import { useToast } from '../../components/Toast'

export const DECISIONS: { value: ReviewDecision; label: string; hint: string }[] = [
  { value: 'confirm_failure', label: 'Confirm failure', hint: 'The machine grade is right: this output fails the contract.' },
  { value: 'acceptable_variation', label: 'Acceptable variation', hint: 'The output is acceptable although it differs.' },
  { value: 'ambiguous', label: 'Ambiguous / needs label', hint: 'The contract or label is unclear. A reason is required.' },
  { value: 'grader_incorrect', label: 'Grader incorrect', hint: 'The grader judged this wrongly. A reason is required.' },
  { value: 'request_more_trials', label: 'Request more trials', hint: 'Creates a linked run with fresh repeats for this case.' },
  { value: 'promote_to_regression', label: 'Promote to regression', hint: 'Adds this case to a regression dataset with an explicit expected contract.' },
]

const REASON_REQUIRED: ReviewDecision[] = ['ambiguous', 'grader_incorrect']
const PROMOTABLE: ReviewDecision[] = ['confirm_failure', 'promote_to_regression']

export function validateReview(decision: ReviewDecision | null, reason: string, reviewer: string): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!decision) errors.decision = 'Choose a decision'
  if (!reviewer.trim()) errors.reviewer = 'Enter your reviewer name (saved in this browser)'
  if (decision && REASON_REQUIRED.includes(decision) && !reason.trim()) errors.reason = 'A reason is required for this decision'
  return errors
}

export function currentReviews(reviews: Review[]): Review[] {
  const superseded = new Set(reviews.map((r) => r.supersedes_id).filter(Boolean))
  return reviews.filter((r) => !superseded.has(r.id))
}

function Promote({ trial, review }: { trial: TrialDetail; review: Review }) {
  const { projectId } = useProject()
  const datasets = useDatasets(projectId, trial.scenario_contract.id)
  const [expected, setExpected] = useState(() => JSON.stringify(trial.case.expected, null, 2))
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const toast = useToast()
  const queryClient = useQueryClient()
  const parsed = parseJsonObject(expected, 'Expected contract')
  const promote = useMutation({
    mutationFn: () =>
      api.post<{ dataset: Dataset; note: string }>('/regressions', {
        run_id: trial.run_id,
        items: [{ trial_id: trial.id, review_id: review.id, expected: parsed.value }],
        target_dataset_id: target || null,
        name: name || null,
      }),
    onSuccess: ({ data }) => {
      toast(data.note)
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
  })
  const regressionSets = (datasets.data ?? []).filter((d) => d.provenance.source === 'regression_promotion' || d.name.startsWith('regression'))
  return (
    <div className="stack card card-muted" data-testid="promote">
      <strong>Promote to a regression dataset</strong>
      <p className="tiny muted">Creates a new dataset version linked to this run, trial and review. The source run is unchanged.</p>
      <Field id="promote-expected" label="Expected contract (JSON)" error={parsed.error} hint="State exactly what a correct output must satisfy.">
        {(props) => <textarea {...props} rows={6} value={expected} onChange={(e) => setExpected(e.target.value)} />}
      </Field>
      <Field id="promote-target" label="Add to dataset">
        {(props) => (
          <select {...props} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">New regression dataset</option>
            {regressionSets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} v{d.version}
              </option>
            ))}
          </select>
        )}
      </Field>
      {!target && (
        <Field id="promote-name" label="Dataset name (optional)">
          {(props) => <input {...props} value={name} onChange={(e) => setName(e.target.value)} placeholder={`regression · ${trial.scenario_contract.name}`} />}
        </Field>
      )}
      <button type="button" className="btn btn-primary" disabled={!!parsed.error || promote.isPending} onClick={() => promote.mutate()}>
        Create regression version
      </button>
      <ActionError error={promote.error} />
      {promote.data && (
        <p className="notice ok small" role="status">
          Created{' '}
          <Link to={`/datasets/${promote.data.data.dataset.id}`}>
            {promote.data.data.dataset.name} v{promote.data.data.dataset.version}
          </Link>
          .{' '}
          <Link to={`/runs/new?scenario=${promote.data.data.dataset.scenario_id}&dataset=${promote.data.data.dataset.id}`}>Rerun it</Link>
        </p>
      )}
    </div>
  )
}

export function ReviewPanel({ trial }: { trial: TrialDetail }) {
  const [reviewer, setReviewerName] = useState(getReviewer)
  const [decision, setDecision] = useState<ReviewDecision | null>(null)
  const [reason, setReason] = useState('')
  const [supersede, setSupersede] = useState(true)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [moreRun, setMoreRun] = useState<string | null>(null)
  const reviews = useReviews({ trial_id: trial.id })
  const adjudicated = useAdjudicated(trial.id)
  const queryClient = useQueryClient()
  const toast = useToast()
  const current = currentReviews(reviews.data ?? [])
  const latest = current.at(-1) ?? null

  const create = useMutation({
    mutationFn: async () => {
      const failing = trial.grades.filter((g) => g.verdict !== 'pass').map((g) => g.id)
      const { data } = await api.post<Review>('/reviews', {
        trial_id: trial.id,
        decision,
        reviewer: reviewer.trim(),
        explanation: reason,
        grade_ids: failing,
        supersedes_id: supersede && latest ? latest.id : null,
      })
      if (decision === 'request_more_trials') {
        const more = await api.post<{ id: string }>(`/runs/${trial.run_id}/more-trials`, { case_ids: [trial.case_id], repeats: 5 }, { 'Idempotency-Key': newIdempotencyKey() })
        setMoreRun(more.data.id)
      }
      return data
    },
    onSuccess: () => {
      setReviewer(reviewer)
      setReason('')
      setDecision(null)
      void queryClient.invalidateQueries({ queryKey: ['reviews'] })
      void queryClient.invalidateQueries({ queryKey: ['adjudicated', trial.id] })
      void queryClient.invalidateQueries({ queryKey: ['triage'] })
      toast('Review recorded. Machine grades are unchanged.')
    },
  })

  function submit() {
    const found = validateReview(decision, reason, reviewer)
    setErrors(found)
    if (Object.keys(found).length === 0) create.mutate()
  }

  return (
    <div className="stack-lg" data-testid="review-panel">
      <div className="stack">
        <h2 style={{ fontSize: 16 }}>Review</h2>
        {!getReviewer() && (
          <Field id="reviewer" label="Reviewer name" error={errors.reviewer} hint="Saved in this browser.">
            {(props) => <input {...props} value={reviewer} onChange={(e) => setReviewerName(e.target.value)} />}
          </Field>
        )}
        {getReviewer() && <span className="small muted">Reviewing as {reviewer}</span>}
        <div className="stack" role="radiogroup" aria-label="Decision" aria-describedby={errors.decision ? 'decision-error' : undefined}>
          {DECISIONS.map((d) => (
            <button
              key={d.value}
              type="button"
              role="radio"
              aria-checked={decision === d.value}
              className={`btn${decision === d.value ? ' btn-primary' : ''}`}
              style={{ justifyContent: 'flex-start' }}
              title={d.hint}
              onClick={() => setDecision(d.value)}
            >
              {d.label}
            </button>
          ))}
        </div>
        {errors.decision && (
          <span className="error small" id="decision-error" role="alert">
            {errors.decision}
          </span>
        )}
        {decision && <p className="tiny muted">{DECISIONS.find((d) => d.value === decision)?.hint}</p>}
        <Field id="review-reason" label={`Reason${decision && REASON_REQUIRED.includes(decision) ? ' (required)' : ' (optional)'}`} error={errors.reason}>
          {(props) => <textarea {...props} rows={3} style={{ fontFamily: 'var(--font)', minHeight: 70 }} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        {latest && (
          <label className="checkbox small">
            <input type="checkbox" checked={supersede} onChange={(e) => setSupersede(e.target.checked)} />
            Supersede the latest review ({latest.decision.replace(/_/g, ' ')} by {latest.reviewer})
          </label>
        )}
        <button type="button" className="btn btn-accent" onClick={submit} disabled={create.isPending}>
          Record review
        </button>
        <ActionError error={create.error} />
        {moreRun && (
          <p className="notice info small" role="status">
            Linked run created: <Link to={`/runs/${moreRun}`}>view fresh repeats</Link>.
          </p>
        )}
      </div>

      {latest && PROMOTABLE.includes(latest.decision) && <Promote trial={trial} review={latest} />}

      <div className="stack">
        <h3>Adjudicated view</h3>
        {adjudicated.data ? (
          <div className="stack small" data-testid="adjudicated">
            <span>
              Machine outcome: <StatusBadge kind="outcome" value={adjudicated.data.machine_outcome} />
            </span>
            <span>
              Adjudicated: <StatusBadge kind="outcome" value={adjudicated.data.adjudicated_outcome} /> <span className="muted">from {adjudicated.data.adjudication_source}</span>
            </span>
            {adjudicated.data.disagreement && <Badge tone="warn">! Human review disagrees with the machine grade</Badge>}
            <span className="tiny muted">{adjudicated.data.note}</span>
          </div>
        ) : (
          <span className="small muted">Loading…</span>
        )}
      </div>

      <div className="stack">
        <h3>History</h3>
        {(reviews.data ?? []).length === 0 ? (
          <p className="small muted">No reviews yet.</p>
        ) : (
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }} data-testid="review-history">
            {reviews.data!.map((r) => (
              <li key={r.id} style={{ opacity: r.superseded_by ? 0.65 : 1 }}>
                <strong>{r.decision.replace(/_/g, ' ')}</strong> by {r.reviewer} · {formatDate(r.created_at)}
                {r.superseded_by ? ' · superseded' : ''}
                {r.explanation && <div className="muted">{r.explanation}</div>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}
