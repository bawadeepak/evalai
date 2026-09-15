// Probability Lab: probability quality for one named event, reliability and
// selective prediction on a held-out split, calibration fitting on the
// calibration split only, and repeatability of run outputs.

import * as Slider from '@radix-ui/react-slider'
import * as Tabs from '@radix-ui/react-tabs'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatNumber, formatPercent } from '../api/format'
import { useCalibrations, useJob, useProbabilityEvents, useProbabilityQuality, useProbabilityRecords, useRun, useRunSummary, useRuns } from '../api/hooks'
import type { QualityBlock } from '../api/types'
import { useProject } from '../app/project'
import { ReliabilityDiagram, RiskCoverage } from '../features/probability/Charts'
import { MetricValue } from '../components/MetricValue'
import { ActionError } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { Empty, ErrorState, Loading, Unavailable } from '../components/States'
import { Badge } from '../components/Status'
import { useToast } from '../components/Toast'

function Cards({ block, n, labels, coverage, calibrationLabel }: { block: QualityBlock | null; n: number; labels: number; coverage: number | null; calibrationLabel: string }) {
  return (
    <div className="kpis" data-testid="probability-cards">
      <div className="kpi">
        <div className="kpi-label">Predictions</div>
        <div className="metric-value num">{n}</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">Labels</div>
        <div className="metric-value num">{labels}</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">Label coverage</div>
        <div className="metric-value num">{formatPercent(coverage)}</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">Brier score</div>
        <div className="metric-value num">{formatNumber(block?.brier ?? null, 4)}</div>
        <div className="tiny muted">lower is better</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">Log loss (clipped)</div>
        <div className="metric-value num">{formatNumber(block?.log_loss_clipped ?? null, 4)}</div>
        <div className="tiny muted">ε = {block?.log_loss_epsilon ?? '—'}</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">ECE</div>
        <div className="metric-value num">{formatNumber(block?.ece ?? null, 4)}</div>
        <div className="tiny muted">{block?.bin_method.replace(/_/g, ' ') ?? ''}</div>
      </div>
      <div className="kpi">
        <div className="kpi-label">Calibration version</div>
        <div className="metric-value" style={{ fontSize: 14 }}>
          {calibrationLabel}
        </div>
      </div>
    </div>
  )
}

function FitForm({ projectId, eventDefinition, onFitted }: { projectId: string; eventDefinition: string; onFitted: (id: string) => void }) {
  const [method, setMethod] = useState<'isotonic' | 'logistic'>('isotonic')
  const [fitSplit, setFitSplit] = useState('calibration')
  const [evalSplit, setEvalSplit] = useState('test')
  const [feature, setFeature] = useState<'raw_feature' | 'probability'>('raw_feature')
  const [jobId, setJobId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const start = useMutation({
    mutationFn: () => api.post<{ job_id: string }>('/calibrations', { project_id: projectId, event_definition: eventDefinition, method, fit_split: fitSplit, eval_split: evalSplit, feature }),
    onSuccess: ({ data }) => setJobId(data.job_id),
  })
  const job = useJob(jobId)
  const result = job.data?.result as { ok?: boolean; error?: string; calibration_id?: string } | null | undefined
  useEffect(() => {
    if (result?.ok && result.calibration_id) {
      void queryClient.invalidateQueries({ queryKey: ['calibrations'] })
      onFitted(result.calibration_id)
      toast('Calibrator fitted on the calibration split; plots show held-out results.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.ok, result?.calibration_id])
  return (
    <div className="stack-lg">
      <p className="small muted">
        Fitting uses only the calibration split and requires both classes and at least 30 independent clusters. The held-out test split is
        never used for fitting. Parameters are stored as plain JSON.
      </p>
      <div className="field-row">
        <Field id="fit-method" label="Method">
          {(props) => (
            <select {...props} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
              <option value="isotonic">Isotonic (bounded)</option>
              <option value="logistic">Logistic (unpenalised)</option>
            </select>
          )}
        </Field>
        <Field id="fit-split" label="Fit on split">
          {(props) => (
            <select {...props} value={fitSplit} onChange={(e) => setFitSplit(e.target.value)}>
              <option value="calibration">calibration</option>
              <option value="test">test (held out)</option>
            </select>
          )}
        </Field>
        <Field id="eval-split" label="Evaluate on split">
          {(props) => (
            <select {...props} value={evalSplit} onChange={(e) => setEvalSplit(e.target.value)}>
              <option value="test">test</option>
              <option value="calibration">calibration</option>
            </select>
          )}
        </Field>
        <Field id="fit-feature" label="Feature">
          {(props) => (
            <select {...props} value={feature} onChange={(e) => setFeature(e.target.value as typeof feature)}>
              <option value="raw_feature">Raw feature</option>
              <option value="probability">Stated probability</option>
            </select>
          )}
        </Field>
      </div>
      <div>
        <button type="button" className="btn btn-primary" onClick={() => start.mutate()} disabled={start.isPending || (!!job.data && ['queued', 'running'].includes(job.data.status))}>
          Fit calibrator
        </button>
      </div>
      <ActionError error={start.error} title="Calibration blocked" />
      {job.data && ['queued', 'running'].includes(job.data.status) && <Loading lines={1} label="Fitting" />}
      {result && result.ok === false && (
        <div className="notice bad" role="alert" data-testid="fit-refused">
          Calibration refused: {result.error}
        </div>
      )}
      {result?.ok && (
        <p className="notice ok small" role="status" data-testid="fit-ok">
          Fitted calibration {result.calibration_id?.slice(0, 8)}.
        </p>
      )}
    </div>
  )
}

function Repeatability() {
  const { projectId } = useProject()
  const runs = useRuns(projectId)
  const [runId, setRunId] = useState<string>('')
  const chosen = runId || runs.data?.data.find((r) => r.status.startsWith('completed'))?.id || ''
  const summary = useRunSummary(chosen || null)
  const run = useRun(chosen || null)
  const logprobs = run.data?.manifest?.candidates.map((c) => ({ key: c.key, state: c.config.capabilities.token_logprobs?.state ?? 'unknown', note: c.config.capabilities.token_logprobs?.note ?? '' }))
  return (
    <div className="stack-lg">
      <div className="field" style={{ width: 280 }}>
        <label htmlFor="rep-run">Run</label>
        <select id="rep-run" value={chosen} onChange={(e) => setRunId(e.target.value)}>
          {(runs.data?.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.name || r.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>
      {logprobs && logprobs.every((l) => l.state !== 'supported') && (
        <Unavailable title="Token log-probabilities unavailable" reason={`No candidate in this run offers token log-probabilities (${logprobs.map((l) => `${l.key}: ${l.state}${l.note ? ` — ${l.note}` : ''}`).join('; ')}). No confidence gauge is shown instead of a real one.`} />
      )}
      {!chosen ? (
        <Empty title="No runs yet" />
      ) : summary.isPending ? (
        <Loading />
      ) : summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : (
        <div className="table-wrap">
          <table data-testid="repeatability-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Candidate</th>
                <th className="num">Output categories</th>
                <th className="num">Modal agr.</th>
                <th className="num">Pairwise agr.</th>
                <th className="num">Entropy</th>
                <th className="num">pass@1 / pass@3 / pass@5</th>
                <th className="num">pass^1 / pass^3 / pass^5</th>
                <th>Frequentist (Wilson) pass rate</th>
                <th>Bayesian posterior (Beta)</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.cases.flatMap((c) =>
                Object.entries(c.candidates).map(([key, cs]) => (
                  <tr key={`${c.case_id}-${key}`}>
                    <td>
                      <Link to={`/triage?run=${chosen}&case=${c.case_id}&candidate=${key}`}>{c.external_id}</Link>
                    </td>
                    <td>{key}</td>
                    <td className="num">{cs.counts.distinct_outputs}</td>
                    <td className="num">
                      <MetricValue metric={cs.metrics.modal_agreement} runId={chosen} showCounts={false} />
                    </td>
                    <td className="num">
                      <MetricValue metric={cs.metrics.pairwise_agreement} runId={chosen} showCounts={false} />
                    </td>
                    <td className="num">
                      <MetricValue metric={cs.metrics.entropy} runId={chosen} showCounts={false} />
                    </td>
                    <td className="num small">
                      {[1, 3, 5].map((k) => (cs.metrics[`pass_at_${k}`] ? formatPercent(cs.metrics[`pass_at_${k}`]!.value) : `k=${k} n/a`)).join(' / ')}
                    </td>
                    <td className="num small">
                      {[1, 3, 5].map((k) => (cs.metrics[`pass_all_${k}`] ? formatPercent(cs.metrics[`pass_all_${k}`]!.value) : `k=${k} n/a`)).join(' / ')}
                    </td>
                    <td>
                      <MetricValue metric={cs.metrics.pass_rate} runId={chosen} />
                    </td>
                    <td>
                      <MetricValue metric={cs.metrics.posterior} runId={chosen} showCounts={false} />
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted">
        Wilson intervals are frequentist confidence intervals; Beta intervals are Bayesian credible intervals under a Beta(1,1) prior. They
        answer different questions and are labelled separately. pass@k and pass^k are shown only where k does not exceed the graded repeats.
      </p>
    </div>
  )
}

export function ProbabilityPage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const events = useProbabilityEvents(projectId)
  const eventDefinition = params.get('event') ?? events.data?.[0]?.event_definition ?? ''
  const split = params.get('split') ?? 'test'
  const calibrationId = params.get('calibration') ?? ''
  const view = params.get('view') === 'calibrated' ? 'calibrated' : 'raw'
  const [threshold, setThreshold] = useState(0.5)
  const [selectedBin, setSelectedBin] = useState<number | null>(null)
  const calibrations = useCalibrations(projectId, eventDefinition || null)
  const quality = useProbabilityQuality(
    { project_id: projectId, event_definition: eventDefinition, split: split || undefined, calibration_id: calibrationId || undefined, threshold },
    !!projectId && !!eventDefinition,
  )
  const block = quality.data ? (view === 'calibrated' && quality.data.calibrated ? quality.data.calibrated : quality.data.raw) : null
  const members = selectedBin !== null ? block?.bins.find((b) => b.index === selectedBin)?.members ?? [] : []
  const records = useProbabilityRecords({ project_id: projectId, event_definition: eventDefinition, external_ids: members.join(',') }, members.length > 0)
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const calibration = calibrations.data?.find((c) => c.id === calibrationId)

  return (
    <>
      <PageHeader title="Probability Lab" subtitle="Probability quality for one named event — separate from task quality and repeatability." />
      <Content>
        {events.isPending ? (
          <Loading />
        ) : events.isError ? (
          <ErrorState error={events.error} onRetry={() => void events.refetch()} />
        ) : (events.data ?? []).length === 0 ? (
          <Unavailable title="No probability records" reason="This project has no predicted probabilities with labels. Import records or run a probability-calibration scenario. Adapters without log-probabilities do not produce a confidence gauge." />
        ) : (
          <>
            <div className="row" role="group" aria-label="Probability selection">
              <div className="field" style={{ minWidth: 280, flex: '1 1 280px' }}>
                <label htmlFor="prob-event">Event</label>
                <select id="prob-event" value={eventDefinition} onChange={(e) => set('event', e.target.value)}>
                  {events.data!.map((ev) => (
                    <option key={ev.event_definition} value={ev.event_definition}>
                      “{ev.event_definition}” · {ev.method} · {ev.predictions} predictions
                    </option>
                  ))}
                </select>
              </div>
              <div className="field" style={{ width: 170 }}>
                <label htmlFor="prob-split">Split</label>
                <select id="prob-split" value={split} onChange={(e) => set('split', e.target.value)}>
                  <option value="test">test (held out)</option>
                  <option value="calibration">calibration</option>
                  <option value="">all records</option>
                </select>
              </div>
              <div className="field" style={{ width: 240 }}>
                <label htmlFor="prob-calibration">Calibrator</label>
                <select id="prob-calibration" value={calibrationId} onChange={(e) => set('calibration', e.target.value)}>
                  <option value="">None (raw scores)</option>
                  {(calibrations.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.fit_method} v{c.version} · {c.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </div>
              {quality.data?.calibrated && (
                <div className="row" role="group" aria-label="Curve" style={{ alignSelf: 'flex-end' }}>
                  <button type="button" className="btn btn-sm" aria-pressed={view === 'raw'} onClick={() => set('view', null)}>
                    Raw
                  </button>
                  <button type="button" className="btn btn-sm" aria-pressed={view === 'calibrated'} onClick={() => set('view', 'calibrated')}>
                    Calibrated
                  </button>
                </div>
              )}
            </div>
            <p className="small">
              Event: <strong>“{eventDefinition}”</strong>
              {quality.data && ` · score types ${quality.data.score_types.join(', ')} · ${quality.data.clusters} clusters · ${quality.data.classes.positive} positive / ${quality.data.classes.negative} negative`}
              {quality.data?.is_demo && <Badge tone="warn">demo data</Badge>}
            </p>
            {quality.isPending ? (
              <Loading />
            ) : quality.isError ? (
              <ErrorState error={quality.error} onRetry={() => void quality.refetch()} />
            ) : (
              <>
                <Cards
                  block={block}
                  n={quality.data.n_predictions}
                  labels={quality.data.n_labels}
                  coverage={quality.data.label_coverage}
                  calibrationLabel={view === 'calibrated' && calibration ? `${calibration.fit_method} v${calibration.version}` : calibration ? 'raw (calibrator available)' : 'none — raw scores'}
                />
                {!block ? (
                  <Unavailable reason={quality.data.raw_unavailable_reason ?? String((quality.data as unknown as { unavailable_reason?: string }).unavailable_reason ?? 'No labelled predictions in this selection.')} />
                ) : (
                  <Tabs.Root defaultValue="reliability">
                    <Tabs.List className="tabs-list" aria-label="Probability views">
                      <Tabs.Trigger value="reliability" className="tab">
                        Reliability
                      </Tabs.Trigger>
                      <Tabs.Trigger value="selective" className="tab">
                        Selective prediction
                      </Tabs.Trigger>
                      <Tabs.Trigger value="calibrate" className="tab">
                        Calibrate
                      </Tabs.Trigger>
                      <Tabs.Trigger value="repeatability" className="tab">
                        Repeatability
                      </Tabs.Trigger>
                    </Tabs.List>
                    <Tabs.Content value="reliability" className="tab-panel">
                      <div className="grid grid-2">
                        <Section title={`Reliability (${view}, ${split || 'all'} split)`} id="reliability">
                          <ReliabilityDiagram bins={block.bins} label={`${view}, ${split || 'all'}`} selected={selectedBin} onSelect={setSelectedBin} />
                        </Section>
                        <Section title={selectedBin === null ? 'Bin cases' : `Cases in bin ${selectedBin + 1}`} id="bin-cases">
                          {selectedBin === null ? (
                            <p className="muted">Select a bin to see its predictions and labels.</p>
                          ) : records.isPending ? (
                            <Loading />
                          ) : records.isError ? (
                            <ErrorState error={records.error} />
                          ) : (
                            <div className="table-wrap">
                              <table data-testid="bin-records">
                                <thead>
                                  <tr>
                                    <th>Record</th>
                                    <th>Cluster</th>
                                    <th className="num">Probability</th>
                                    <th className="num">Label</th>
                                    <th>Split</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {records.data!.data.map((rec) => (
                                    <tr key={rec.id}>
                                      <td>{rec.trial_id ? <Link to={`/triage?trial=${rec.trial_id}`}>{rec.external_id}</Link> : rec.external_id}</td>
                                      <td className="small">{rec.cluster_id}</td>
                                      <td className="num">{rec.probability === null ? 'Unavailable' : formatPercent(rec.probability)}</td>
                                      <td className="num">{rec.label === null ? 'unlabelled' : rec.label}</td>
                                      <td>{rec.split}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </Section>
                      </div>
                      {quality.data.notes.map((n) => (
                        <p key={n} className="small muted">
                          {n}
                        </p>
                      ))}
                    </Tabs.Content>
                    <Tabs.Content value="selective" className="tab-panel">
                      <div className="grid grid-2">
                        <Section title="Decision threshold" id="threshold">
                          <div className="stack-lg">
                            <div className="stack">
                              <label id="threshold-label" htmlFor="threshold-slider" className="small" style={{ fontWeight: 600 }}>
                                Accept predictions with probability ≥ {threshold.toFixed(2)}
                              </label>
                              <Slider.Root className="slider" value={[threshold]} min={0} max={1} step={0.05} onValueChange={(v) => setThreshold(v[0] ?? 0.5)} aria-labelledby="threshold-label">
                                <Slider.Track className="slider-track">
                                  <Slider.Range className="slider-range" />
                                </Slider.Track>
                                <Slider.Thumb className="slider-thumb" id="threshold-slider" aria-label="Decision threshold" />
                              </Slider.Root>
                            </div>
                            <div className="kpis">
                              <div className="kpi">
                                <div className="kpi-label">Coverage</div>
                                <div className="metric-value num">{formatPercent(block.selective.coverage)}</div>
                              </div>
                              <div className="kpi">
                                <div className="kpi-label">Selective risk</div>
                                <div className="metric-value num" data-testid="selective-risk">
                                  {block.selective.risk === null ? 'Unavailable: no accepted predictions' : formatPercent(block.selective.risk)}
                                </div>
                              </div>
                              <div className="kpi">
                                <div className="kpi-label">Accepted / review</div>
                                <div className="metric-value num">
                                  {block.selective.accepted} / {block.selective.review}
                                </div>
                              </div>
                            </div>
                            <p className="small muted">Evaluated on the “{split || 'all records'}” split{split === 'test' ? ' (held out)' : ''}.</p>
                          </div>
                        </Section>
                        <Section title="Risk–coverage" id="risk-coverage">
                          <RiskCoverage points={block.risk_coverage} threshold={threshold} />
                        </Section>
                      </div>
                    </Tabs.Content>
                    <Tabs.Content value="calibrate" className="tab-panel">
                      <Section title="Fit a calibrator" id="fit">
                        {projectId && (
                          <FitForm
                            projectId={projectId}
                            eventDefinition={eventDefinition}
                            onFitted={(id) => {
                              const next = new URLSearchParams(params)
                              next.set('calibration', id)
                              next.set('view', 'calibrated')
                              setParams(next, { replace: true })
                            }}
                          />
                        )}
                      </Section>
                    </Tabs.Content>
                    <Tabs.Content value="repeatability" className="tab-panel">
                      <Repeatability />
                    </Tabs.Content>
                  </Tabs.Root>
                )}
              </>
            )}
          </>
        )}
      </Content>
    </>
  )
}
