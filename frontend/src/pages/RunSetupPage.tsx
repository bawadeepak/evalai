// Run setup: fully resolved configuration, plan and capability validation
// before anything is enqueued. Run is disabled while there are errors, and
// each error links to the control (or provider) that causes it.

import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, fieldErrors, newIdempotencyKey } from '../api/client'
import { useDatasets, useRun, useScenario, useScenarios, useTargets } from '../api/hooks'
import type { RunValidation, TargetConfig } from '../api/types'
import { useProject } from '../app/project'
import { Json } from '../components/Content'
import { ActionError, Hash, KeyValue } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { Loading } from '../components/States'
import { Badge, StatusBadge } from '../components/Status'

export type SetupForm = {
  name: string
  scenarioId: string
  datasetId: string
  baselineId: string
  candidateIds: string[]
  graderIds: string[] | null
  repeats: number
  repeatMode: 'full_episode' | 'frozen_context'
  maxConcurrency: string
  scheduleSeed: number
  maxTargetCalls: string
  maxJudgeCalls: string
  maxCost: string
  timeoutSeconds: number
}

const optionalInt = (text: string) => (text.trim() === '' ? null : Number(text))

export function candidateKey(index: number): string {
  return index === 0 ? 'candidate' : `candidate-${index + 1}`
}

export function buildRunRequest(form: SetupForm, projectId: string | null) {
  const candidates = [
    ...(form.baselineId ? [{ key: 'baseline', target_config_id: form.baselineId }] : []),
    ...form.candidateIds.filter(Boolean).map((id, i) => ({ key: candidateKey(i), target_config_id: id })),
  ]
  return {
    project_id: projectId,
    scenario_id: form.scenarioId,
    dataset_id: form.datasetId,
    name: form.name.trim(),
    candidates,
    grader_ids: form.graderIds,
    execution: {
      repeats: form.repeats,
      repeat_mode: form.repeatMode,
      max_concurrency: optionalInt(form.maxConcurrency),
      schedule_seed: form.scheduleSeed,
    },
    limits: {
      max_target_calls: optionalInt(form.maxTargetCalls),
      max_judge_calls: optionalInt(form.maxJudgeCalls),
      max_cost: form.maxCost.trim() === '' ? null : Number(form.maxCost),
      timeout_seconds: form.timeoutSeconds,
    },
  }
}

/** Map a server error field (e.g. candidates[1].parameters.seed) to the id of the control that fixes it. */
export function controlFor(field: string, hasBaseline: boolean): string | null {
  const candidate = /^candidates[[.](\d+)/.exec(field)
  if (candidate) {
    const index = Number(candidate[1])
    if (hasBaseline) return index === 0 ? 'run-baseline' : `run-candidate-${index - 1}`
    return `run-candidate-${index}`
  }
  const map: Record<string, string> = {
    scenario_id: 'run-scenario',
    dataset_id: 'run-dataset',
    grader_ids: 'run-graders',
    'execution.repeats': 'run-repeats',
    'execution.repeat_mode': 'run-repeat-mode',
    'execution.max_concurrency': 'run-concurrency',
    'limits.max_target_calls': 'run-max-target',
    'limits.max_judge_calls': 'run-max-judge',
    'limits.max_cost': 'run-max-cost',
    'limits.timeout_seconds': 'run-timeout',
    candidates: 'run-candidate-0',
  }
  return map[field] ?? null
}

function configFor(field: string, request: ReturnType<typeof buildRunRequest>): string | null {
  const match = /^candidates[[.](\d+)/.exec(field)
  return match ? request.candidates[Number(match[1])]?.target_config_id ?? null : null
}

function focusControl(id: string) {
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ block: 'center' })
    el.focus()
  }
}

function TargetSelect({ id, value, onChange, targets, label, optional, error }: {
  id: string
  value: string
  onChange: (value: string) => void
  targets: TargetConfig[]
  label: string
  optional?: boolean
  error?: string | null
}) {
  return (
    <Field id={id} label={label} error={error}>
      {(props) => (
        <select {...props} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{optional ? 'No baseline' : 'Select a provider configuration…'}</option>
          {targets.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} v{t.version} · {t.adapter}
              {t.model ? ` · ${t.model}` : ''}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

export function RunSetupPage() {
  const { projectId } = useProject()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const scenarios = useScenarios(projectId)
  const targets = useTargets(projectId)
  const cloneRun = useRun(params.get('clone'))
  const [form, setForm] = useState<SetupForm>(() => ({
    name: '',
    scenarioId: params.get('scenario') ?? '',
    datasetId: params.get('dataset') ?? '',
    baselineId: params.get('baseline') ?? '',
    candidateIds: [params.get('candidate') ?? ''],
    graderIds: null,
    repeats: 5,
    repeatMode: 'full_episode',
    maxConcurrency: '',
    scheduleSeed: 42,
    maxTargetCalls: '',
    maxJudgeCalls: '',
    maxCost: '',
    timeoutSeconds: 120,
  }))
  const update = (patch: Partial<SetupForm>) => setForm((f) => ({ ...f, ...patch }))

  const cloned = useRef(false)
  useEffect(() => {
    const manifest = cloneRun.data?.manifest
    if (!manifest || cloned.current) return
    cloned.current = true
    const ordered = [...manifest.candidates].sort((a, b) => a.ordinal - b.ordinal)
    const baseline = ordered.find((c) => c.key === 'baseline')
    const rest = ordered.filter((c) => c.key !== 'baseline')
    setForm((f) => ({
      ...f,
      name: `${cloneRun.data?.name ?? 'run'} (clone)`,
      scenarioId: manifest.scenario.id,
      datasetId: manifest.dataset.id,
      baselineId: baseline?.config.id ?? '',
      candidateIds: rest.length ? rest.map((c) => c.config.id) : [''],
      graderIds: manifest.graders.map((g) => g.id),
      repeats: Number(manifest.execution.repeats ?? 5),
      repeatMode: (manifest.execution.repeat_mode as SetupForm['repeatMode']) ?? 'full_episode',
      scheduleSeed: Number(manifest.execution.schedule_seed ?? 42),
      timeoutSeconds: Number(manifest.limits.timeout_seconds ?? 120),
    }))
  }, [cloneRun.data])

  const scenario = useScenario(form.scenarioId || null)
  const datasets = useDatasets(projectId, form.scenarioId || null)
  useEffect(() => {
    const list = datasets.data ?? []
    if (form.scenarioId && list.length && !list.some((d) => d.id === form.datasetId)) update({ datasetId: list[0]!.id })
  }, [datasets.data, form.scenarioId, form.datasetId])

  const request = useMemo(() => buildRunRequest(form, projectId), [form, projectId])
  const requestKey = JSON.stringify(request)
  const [debouncedKey, setDebouncedKey] = useState(requestKey)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKey(requestKey), 300)
    return () => clearTimeout(timer)
  }, [requestKey])
  const ready = !!(projectId && form.scenarioId && form.datasetId && request.candidates.some((c) => c.key !== 'baseline'))
  const validation = useQuery({
    queryKey: ['run-validate', debouncedKey],
    queryFn: () => api.post<RunValidation>('/runs/validate', JSON.parse(debouncedKey)),
    enabled: ready,
    retry: false,
    staleTime: 0,
  })
  const idempotencyKey = useMemo(() => newIdempotencyKey(), [debouncedKey])
  const create = useMutation({
    mutationFn: () => api.post<{ id: string }>('/runs', JSON.parse(debouncedKey), { 'Idempotency-Key': idempotencyKey }),
    onSuccess: ({ data }) => navigate(`/runs/${data.id}`),
  })

  const errors = fieldErrors(validation.error)
  const errorEntries = Object.entries(errors)
  const hasBaseline = !!form.baselineId
  const controlError = (id: string) => errorEntries.filter(([field]) => controlFor(field, hasBaseline) === id).map(([, m]) => m).join(' ') || null
  const stale = debouncedKey !== requestKey
  const canRun = ready && !!validation.data && !validation.isFetching && !stale && !create.isPending
  const plan = validation.data?.data.plan
  const manifest = validation.data?.data.manifest
  const mandatory = new Set(datasets.data?.find((d) => d.id === form.datasetId)?.pass_rule.mandatory_graders ?? [])
  const scenarioGraders = scenario.data?.graders ?? []
  const selectedGraders = form.graderIds ?? scenarioGraders.map((g) => g.id)
  const isMemory = scenario.data?.pack === 'memory_lifecycle'
  const targetList = targets.data ?? []

  return (
    <>
      <PageHeader
        title="Run setup"
        subtitle="Everything below is validated against capabilities before the run is enqueued."
        actions={
          <button type="button" className="btn btn-primary" disabled={!canRun} onClick={() => create.mutate()} data-testid="start-run">
            {create.isPending ? 'Starting…' : 'Run'}
          </button>
        }
      />
      <Content>
        {params.get('clone') && cloneRun.isPending && <Loading lines={1} label="Loading the run to clone" />}
        <div className="grid grid-2">
          <Section title="What to evaluate" id="setup-what">
            <div className="stack-lg">
              <Field id="run-name" label="Run name (optional)">
                {(props) => <input {...props} value={form.name} onChange={(e) => update({ name: e.target.value })} />}
              </Field>
              <Field id="run-scenario" label="Scenario" error={controlError('run-scenario')}>
                {(props) => (
                  <select {...props} value={form.scenarioId} onChange={(e) => update({ scenarioId: e.target.value, datasetId: '', graderIds: null })}>
                    <option value="">Select a scenario…</option>
                    {(scenarios.data ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} v{s.version} · {s.pack.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field id="run-dataset" label="Dataset version" error={controlError('run-dataset')}>
                {(props) => (
                  <select {...props} value={form.datasetId} onChange={(e) => update({ datasetId: e.target.value })} disabled={!form.scenarioId}>
                    <option value="">Select a dataset…</option>
                    {(datasets.data ?? []).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} v{d.version} · {d.case_count} cases
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <TargetSelect id="run-baseline" label="Baseline (optional)" optional value={form.baselineId} onChange={(v) => update({ baselineId: v })} targets={targetList} error={controlError('run-baseline')} />
              {form.candidateIds.map((id, index) => (
                <div key={index} className="row" style={{ alignItems: 'flex-end', flexWrap: 'nowrap' }}>
                  <div className="grow">
                    <TargetSelect
                      id={`run-candidate-${index}`}
                      label={index === 0 ? 'Candidate' : `Candidate ${index + 1}`}
                      value={id}
                      onChange={(v) => update({ candidateIds: form.candidateIds.map((c, i) => (i === index ? v : c)) })}
                      targets={targetList}
                      error={controlError(`run-candidate-${index}`)}
                    />
                  </div>
                  {index > 0 && (
                    <button type="button" className="btn btn-sm" onClick={() => update({ candidateIds: form.candidateIds.filter((_, i) => i !== index) })}>
                      Remove
                    </button>
                  )}
                </div>
              ))}
              {form.candidateIds.length + (form.baselineId ? 1 : 0) < 4 && (
                <div>
                  <button type="button" className="btn btn-sm" onClick={() => update({ candidateIds: [...form.candidateIds, ''] })}>
                    Add candidate
                  </button>
                </div>
              )}
            </div>
          </Section>
          <Section title="How to run it" id="setup-how">
            <div className="stack-lg">
              <div className="field-row">
                <Field id="run-repeats" label="Repeats per case" hint="Integer ≥ 1. Each repeat is a fresh execution; outputs are never cached." error={controlError('run-repeats')}>
                  {(props) => (
                    <input {...props} type="number" min={1} step={1} value={form.repeats} onChange={(e) => update({ repeats: Math.max(0, Math.floor(Number(e.target.value))) })} />
                  )}
                </Field>
                {isMemory && (
                  <Field id="run-repeat-mode" label="Memory repeat mode" hint="full_episode re-runs every step in a fresh isolated store." error={controlError('run-repeat-mode')}>
                    {(props) => (
                      <select {...props} value={form.repeatMode} onChange={(e) => update({ repeatMode: e.target.value as SetupForm['repeatMode'] })}>
                        <option value="full_episode">Full episode</option>
                        <option value="frozen_context">Frozen context</option>
                      </select>
                    )}
                  </Field>
                )}
                <Field id="run-concurrency" label="Max concurrency (optional)" hint="Default: MemoryAI 1, stateless 2">
                  {(props) => <input {...props} type="number" min={1} max={16} value={form.maxConcurrency} onChange={(e) => update({ maxConcurrency: e.target.value })} />}
                </Field>
                <Field id="run-seed" label="Schedule seed">
                  {(props) => <input {...props} type="number" value={form.scheduleSeed} onChange={(e) => update({ scheduleSeed: Number(e.target.value) })} />}
                </Field>
              </div>
              <fieldset id="run-graders" tabIndex={-1}>
                <legend>Graders</legend>
                {controlError('run-graders') && <p className="error small">{controlError('run-graders')}</p>}
                {scenarioGraders.length === 0 ? (
                  <p className="small muted">Select a scenario to see its graders.</p>
                ) : (
                  <div className="stack">
                    {scenarioGraders.map((g) => (
                      <label key={g.id} className="checkbox">
                        <input
                          type="checkbox"
                          checked={selectedGraders.includes(g.id)}
                          disabled={mandatory.has(g.name)}
                          onChange={(e) =>
                            update({ graderIds: e.target.checked ? [...selectedGraders, g.id] : selectedGraders.filter((x) => x !== g.id) })
                          }
                        />
                        <span>
                          {g.name} <span className="muted small">({g.kind}, v{g.version})</span>
                          {mandatory.has(g.name) && <Badge tone="info">mandatory</Badge>}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </fieldset>
              <div className="field-row">
                <Field id="run-max-target" label="Max target calls" error={controlError('run-max-target')}>
                  {(props) => <input {...props} type="number" min={1} value={form.maxTargetCalls} onChange={(e) => update({ maxTargetCalls: e.target.value })} />}
                </Field>
                <Field id="run-max-judge" label="Max judge calls" error={controlError('run-max-judge')}>
                  {(props) => <input {...props} type="number" min={0} value={form.maxJudgeCalls} onChange={(e) => update({ maxJudgeCalls: e.target.value })} />}
                </Field>
                <Field id="run-max-cost" label="Max cost" hint="Needs known pricing for every model" error={controlError('run-max-cost')}>
                  {(props) => <input {...props} type="number" min={0} step="0.01" value={form.maxCost} onChange={(e) => update({ maxCost: e.target.value })} />}
                </Field>
                <Field id="run-timeout" label="Timeout per action (s)" error={controlError('run-timeout')}>
                  {(props) => <input {...props} type="number" min={1} value={form.timeoutSeconds} onChange={(e) => update({ timeoutSeconds: Number(e.target.value) })} />}
                </Field>
              </div>
            </div>
          </Section>
        </div>

        <Section title="Validation" id="setup-validation">
          {!ready ? (
            <p className="muted">Choose a scenario, a dataset and at least one candidate.</p>
          ) : validation.isFetching || stale ? (
            <Loading lines={1} label="Validating the run" />
          ) : validation.isError ? (
            <div className="notice bad" role="alert" data-testid="run-errors">
              <div className="stack" style={{ gap: 6 }}>
                <strong>Run is disabled until these are fixed</strong>
                <ul style={{ margin: 0, paddingLeft: 18 }} className="stack">
                  {errorEntries.length === 0 && <li>{(validation.error as Error).message}</li>}
                  {errorEntries.map(([field, message]) => {
                    const control = controlFor(field, hasBaseline)
                    const configId = configFor(field, request)
                    return (
                      <li key={field}>
                        <code>{field}</code>: {message}{' '}
                        {control && (
                          <button type="button" className="link-button" onClick={() => focusControl(control)}>
                            Go to control
                          </button>
                        )}
                        {configId && field.includes('parameters') && (
                          <>
                            {' · '}
                            <Link to={`/providers?config=${configId}&edit=1`}>Edit provider as new version</Link>
                          </>
                        )}
                      </li>
                    )
                  })}
                </ul>
                {validation.error instanceof ApiError && validation.error.status !== 422 && <span className="small">{validation.error.message}</span>}
              </div>
            </div>
          ) : validation.data ? (
            <div className="notice ok" role="status" data-testid="run-valid">
              <span aria-hidden="true">✓</span>
              <span>
                Valid. {validation.data.data.warnings.length ? `${validation.data.data.warnings.length} warning(s) below.` : ''}
                {validation.data.data.is_demo ? ' Demo run: outputs are synthetic fixtures.' : ''}
              </span>
            </div>
          ) : null}
          {validation.data?.data.warnings.map((w) => (
            <p key={w} className="notice warn small">
              {w}
            </p>
          ))}
          <ActionError error={create.error} title="The run was not created" />
        </Section>

        {plan && manifest && !stale && (
          <>
            <Section title="Plan" id="setup-plan">
              <div className="kpis">
                <div className="kpi" data-testid="planned-trials">
                  <div className="kpi-label">Planned target executions</div>
                  <div className="metric-value num">
                    {plan.cases} × {plan.candidates} × {plan.repeats} = {plan.planned_trials}
                  </div>
                  <div className="tiny muted">cases × candidates × repeats</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Stage calls per episode</div>
                  <div className="metric-value num">{plan.stage_calls_per_episode}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Target calls (estimate)</div>
                  <div className="metric-value num">{plan.target_calls_estimate}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Judge calls (estimate)</div>
                  <div className="metric-value num">{plan.judge_calls_estimate}</div>
                  <div className="tiny muted">{plan.judge_calls_note}</div>
                </div>
              </div>
              <h3 style={{ marginTop: 14 }}>Estimated cost</h3>
              <KeyValue
                items={Object.entries(plan.cost_estimates).map(([key, value]) => {
                  const v = value as Record<string, unknown> | null
                  const text =
                    v && typeof v === 'object' && v.amount !== null && v.amount !== undefined
                      ? `${String(v.amount)} ${String(v.currency ?? '')} (estimate)`
                      : `Unknown${v && typeof v === 'object' && v.reason ? ` — ${String(v.reason)}` : ' — no pricing entry'}`
                  return [key, text]
                })}
              />
              <p className="small muted">Manifest hash <Hash value={validation.data?.data.manifest_hash} /></p>
            </Section>
            <Section title="Resolved configuration" id="setup-resolved">
              <div className="stack-lg">
                {manifest.candidates.map((c) => (
                  <details key={c.key} open>
                    <summary>
                      <strong>{c.key}</strong>: {c.config.name} · {c.config.adapter}/{c.config.endpoint_type} · {c.config.requested_model || 'no model'}
                    </summary>
                    <div className="grid grid-2" style={{ marginTop: 8 }}>
                      <div className="stack">
                        <KeyValue
                          items={[
                            ['Credential', c.config.credential_ref ? <code key="c">{c.config.credential_ref}</code> : 'not required'],
                            ['Base URL', c.config.base_url ?? '—'],
                            ['Experimental', c.config.experimental ? 'yes' : 'no'],
                            ['Config hash', <Hash key="h" value={c.config.hash} />],
                          ]}
                        />
                        <h4>Parameters</h4>
                        <Json value={c.config.parameters} />
                        {c.config.prompt_template && (
                          <>
                            <h4>Prompt template</h4>
                            <pre className="box">{c.config.prompt_template}</pre>
                          </>
                        )}
                        {c.config.tools.length > 0 && (
                          <>
                            <h4>Tools</h4>
                            <Json value={c.config.tools} />
                          </>
                        )}
                        {Object.keys(c.config.memory_config).length > 0 && (
                          <>
                            <h4>Memory configuration</h4>
                            <Json value={c.config.memory_config} />
                          </>
                        )}
                      </div>
                      <div>
                        <h4>Capability snapshot</h4>
                        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0, gap: 3 }}>
                          {Object.entries(c.config.capabilities).map(([name, cap]) => (
                            <li key={name} className="row-between small">
                              <span>{name.replace(/_/g, ' ')}</span>
                              <StatusBadge kind="capability" value={cap.state} title={`${cap.source}${cap.note ? ` — ${cap.note}` : ''}`} />
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </details>
                ))}
                <div className="grid grid-2">
                  <div>
                    <h4>Graders and judges</h4>
                    <ul>
                      {manifest.graders.map((g) => (
                        <li key={g.id}>
                          {g.name} ({g.kind}){g.judge_config_id ? ` — judge ${targetList.find((t) => t.id === g.judge_config_id)?.name ?? g.judge_config_id.slice(0, 8)}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4>Execution and isolation</h4>
                    <Json value={{ execution: manifest.execution, limits: manifest.limits }} />
                  </div>
                </div>
              </div>
            </Section>
          </>
        )}
      </Content>
    </>
  )
}
