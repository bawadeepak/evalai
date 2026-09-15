import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Fragment, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, downloadFile } from '../api/client'
import { formatDate } from '../api/format'
import { useCases, useDataset, usePacks } from '../api/hooks'
import type { Case, Dataset, SplitManifest, ValidationReport } from '../api/types'
import { useProject } from '../app/project'
import { readJson, writeJson } from '../app/storage'
import { Dialog } from '../components/Dialog'
import { Json } from '../components/Content'
import { ActionError, Hash, KeyValue } from '../components/Misc'
import { Content, Field, PageHeader, parseJsonArray, Section } from '../components/Page'
import { ErrorState, Loading } from '../components/States'
import { Badge, SeverityBadge } from '../components/Status'
import { useToast } from '../components/Toast'
import { ValidationList } from './ScenarioWizardPage'

const PAGE = 50

function preview(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text && text.length > 90 ? `${text.slice(0, 90)}…` : text ?? ''
}

function SplitDialog({ dataset, open, onOpenChange }: { dataset: Dataset; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [calibration, setCalibration] = useState(50)
  const [seed, setSeed] = useState(42)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const body = { fractions: { calibration: calibration / 100, test: 1 - calibration / 100 }, seed }
  const dryRun = useMutation({ mutationFn: () => api.post<{ split_manifest: SplitManifest }>(`/datasets/${dataset.id}/split`, { ...body, dry_run: true }) })
  const apply = useMutation({
    mutationFn: () => api.post<{ dataset: Dataset }>(`/datasets/${dataset.id}/split`, { ...body, dry_run: false, reason: `cluster-aware split ${calibration}/${100 - calibration}` }),
    onSuccess: ({ data }) => {
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      onOpenChange(false)
      navigate(`/datasets/${data.dataset.id}`)
    },
  })
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Split by cluster"
      description="Whole clusters are assigned to one split, so related cases never straddle calibration and test. Applying creates a new dataset version."
      footer={
        <>
          <button type="button" className="btn" onClick={() => dryRun.mutate()} disabled={dryRun.isPending}>
            Preview
          </button>
          <button type="button" className="btn btn-primary" onClick={() => apply.mutate()} disabled={!dryRun.data || apply.isPending}>
            Create split version
          </button>
        </>
      }
    >
      <div className="field-row">
        <Field id="split-cal" label="Calibration share (%)">
          {(props) => <input {...props} type="number" min={5} max={95} value={calibration} onChange={(e) => setCalibration(Number(e.target.value))} />}
        </Field>
        <Field id="split-seed" label="Seed">
          {(props) => <input {...props} type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />}
        </Field>
      </div>
      <ActionError error={dryRun.error ?? apply.error} />
      {dryRun.data && <Json value={dryRun.data.data.split_manifest} label="Split preview" />}
    </Dialog>
  )
}

function CaseEditor({ dataset, onClose }: { dataset: Dataset; onClose: () => void }) {
  const draftKey = `evalai.caseDraft.${dataset.id}`
  const { projectId } = useProject()
  const [text, setText] = useState<string>(() => readJson<string>(draftKey) ?? '')
  const [reason, setReason] = useState('')
  const [validated, setValidated] = useState<{ text: string; report: ValidationReport } | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const load = useMutation({
    mutationFn: () => api.get<Record<string, unknown>[]>(`/datasets/${dataset.id}/export`),
    onSuccess: ({ data }) => setText(JSON.stringify(data, null, 2)),
  })
  useEffect(() => {
    if (!text) load.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => writeJson(draftKey, text || null), [draftKey, text])
  const parsed = parseJsonArray(text, 'Cases')
  const validate = useMutation({
    mutationFn: () => api.post<ValidationReport>('/datasets/validate', { scenario_id: dataset.scenario_id, cases: parsed.value }),
    onSuccess: ({ data }) => setValidated({ text, report: data }),
  })
  const publish = useMutation({
    mutationFn: () =>
      api.post<Dataset>('/datasets', {
        project_id: projectId,
        scenario_id: dataset.scenario_id,
        name: dataset.name,
        cases: parsed.value,
        parent_id: dataset.id,
        reason: reason || 'edited in case editor',
      }),
    onSuccess: ({ data }) => {
      writeJson(draftKey, null)
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      toast(`Published ${data.name} v${data.version}`)
      onClose()
      navigate(`/datasets/${data.id}`)
    },
  })
  const ok = validated?.text === text && validated.report.ok
  return (
    <Section title="Case editor (draft)" id="case-editor">
      <div className="stack-lg">
        <p className="small muted">
          Edit the cases as JSON. Publishing creates v{dataset.version + 1}; this version is never modified. The draft is kept in this
          browser.
        </p>
        <Field id="case-json" label="Cases" error={parsed.error}>
          {(props) => <textarea {...props} rows={18} value={text} onChange={(e) => setText(e.target.value)} />}
        </Field>
        <Field id="case-reason" label="Reason for the new version">
          {(props) => <input {...props} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <div className="row">
          <button type="button" className="btn" disabled={!!parsed.error || validate.isPending} onClick={() => validate.mutate()}>
            Validate
          </button>
          <button type="button" className="btn btn-primary" disabled={!ok || publish.isPending} onClick={() => publish.mutate()}>
            Publish new version
          </button>
          <button type="button" className="btn" onClick={() => { writeJson(draftKey, null); onClose() }}>
            Discard draft
          </button>
        </div>
        {validated && validated.text === text && <ValidationList report={validated.report} />}
        <ActionError error={load.error ?? validate.error ?? publish.error} />
      </div>
    </Section>
  )
}

export function DatasetDetailPage() {
  const { id } = useParams()
  const dataset = useDataset(id)
  const packs = usePacks()
  const [offset, setOffset] = useState(0)
  const [split, setSplit] = useState('')
  const cases = useCases(id, { limit: PAGE, offset, split: split || undefined })
  const [open, setOpen] = useState<string | null>(null)
  const [splitting, setSplitting] = useState(false)
  const [editing, setEditing] = useState(false)

  if (dataset.isPending)
    return (
      <>
        <PageHeader title="Dataset" />
        <Content>
          <Loading />
        </Content>
      </>
    )
  if (dataset.isError)
    return (
      <>
        <PageHeader title="Dataset" />
        <Content>
          <ErrorState error={dataset.error} onRetry={() => void dataset.refetch()} />
        </Content>
      </>
    )
  const ds = dataset.data
  const total = Number(cases.data?.meta.total ?? ds.case_count)
  const rows: Case[] = cases.data?.data ?? []
  const pack = packs.data?.packs.find((p) => p.pack === ds.scenario.pack)
  const severityCounts = rows.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.severity]: (acc[c.severity] ?? 0) + 1 }), {})

  return (
    <>
      <PageHeader
        title={`${ds.name} · v${ds.version}`}
        subtitle={
          <>
            Scenario <Link to={`/scenarios/${ds.scenario.id}`}>{ds.scenario.name} v{ds.scenario.version}</Link> · {ds.case_count} cases
          </>
        }
        actions={
          <>
            <button type="button" className="btn" onClick={() => void downloadFile(`/datasets/${ds.id}/export`, `${ds.name}-v${ds.version}.jsonl`, { format: 'jsonl' })}>
              Export JSONL
            </button>
            <button type="button" className="btn" onClick={() => setSplitting(true)}>
              Split by cluster
            </button>
            <button type="button" className="btn" onClick={() => setEditing(true)}>
              Edit as new version
            </button>
            <Link to={`/runs/new?scenario=${ds.scenario.id}&dataset=${ds.id}`} className="btn btn-primary">
              Run
            </Link>
          </>
        }
      />
      <Content>
        {editing && <CaseEditor dataset={ds} onClose={() => setEditing(false)} />}
        <div className="grid grid-2">
          <Section title="Summary" id="summary">
            <KeyValue
              items={[
                ['Pass rule', `${ds.pass_rule.policy.replace(/_/g, ' ')}: ${ds.pass_rule.mandatory_graders.join(', ')}`],
                ['Clusters', ds.split_manifest?.cluster_count ?? '—'],
                ['Hash', <Hash key="h" value={ds.hash} />],
                ['Created', formatDate(ds.created_at)],
                ['Reason', ds.reason || '—'],
                ['Provenance', <code key="p" className="tiny">{JSON.stringify(ds.provenance)}</code>],
              ]}
            />
          </Section>
          <Section title="Splits and coverage" id="coverage">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Split</th>
                    <th className="num">Cases</th>
                    <th className="num">Clusters</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(ds.split_manifest?.splits ?? {}).map(([name, v]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="num">{v.cases}</td>
                      <td className="num">{v.clusters}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ds.split_manifest?.leaking_clusters?.length ? (
              <p className="notice warn small">Clusters spanning splits: {ds.split_manifest.leaking_clusters.join(', ')}</p>
            ) : (
              <p className="small muted">No cluster spans more than one split.</p>
            )}
            {ds.duplicates.length > 0 ? (
              <p className="notice warn small">Duplicate content: {ds.duplicates.map((d) => d.join(' = ')).join('; ')}</p>
            ) : (
              <p className="small muted">No duplicate cases detected.</p>
            )}
            <p className="small muted">
              Severity on this page: {Object.entries(severityCounts).map(([k, v]) => `${v} ${k}`).join(', ') || '—'}
            </p>
          </Section>
        </div>
        <Section
          title="Cases"
          id="cases"
          actions={
            <div className="field" style={{ width: 180 }}>
              <label htmlFor="case-split" className="sr-only">
                Filter by split
              </label>
              <select
                id="case-split"
                value={split}
                onChange={(e) => {
                  setSplit(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">All splits</option>
                {Object.keys(ds.split_manifest?.splits ?? {}).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          {cases.isError ? (
            <ErrorState error={cases.error} onRetry={() => void cases.refetch()} />
          ) : cases.isPending ? (
            <Loading />
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="sticky-col">Case</th>
                      <th>Severity</th>
                      <th>Split</th>
                      <th>Cluster</th>
                      <th>Purpose</th>
                      <th>Input</th>
                      <th>Expected</th>
                      <th>Tags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <Fragment key={c.id}>
                        <tr>
                          <td className="sticky-col">
                            <button type="button" className="link-button" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
                              {c.external_id}
                            </button>
                          </td>
                          <td>
                            <SeverityBadge severity={c.severity} />
                          </td>
                          <td className="small">{c.split}</td>
                          <td className="small">{c.cluster_id}</td>
                          <td className="small" style={{ minWidth: 200 }}>
                            {c.purpose}
                          </td>
                          <td className="small mono">{preview(c.episode.length ? `${c.episode.length} episode steps` : c.input)}</td>
                          <td className="small mono">{preview(c.expected)}</td>
                          <td className="small">
                            {Object.entries(c.tags).map(([k, v]) => (
                              <Badge key={k}>
                                {k}={String(v)}
                              </Badge>
                            ))}
                          </td>
                        </tr>
                        {open === c.id && (
                          <tr>
                            <td colSpan={8}>
                              <div className="grid grid-2">
                                <div className="stack">
                                  <h4>{c.episode.length ? 'Episode' : 'Input'}</h4>
                                  <Json value={c.episode.length ? c.episode : c.input} />
                                </div>
                                <div className="stack">
                                  <h4>Expected</h4>
                                  <Json value={c.expected} />
                                  {c.alternatives.length > 0 && (
                                    <>
                                      <h4>Alternatives</h4>
                                      <Json value={c.alternatives} />
                                    </>
                                  )}
                                  {c.evidence.length > 0 && (
                                    <>
                                      <h4>Evidence</h4>
                                      <Json value={c.evidence} />
                                    </>
                                  )}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row-between" style={{ marginTop: 10 }}>
                <span className="small muted">
                  {total === 0 ? 'No cases' : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`}
                </span>
                <div className="row">
                  <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    Previous
                  </button>
                  <button type="button" className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </Section>
        {pack && (
          <Section title="Schema hints" id="schema-hints">
            <p className="small muted">Expected-value schema for the {pack.title} pack.</p>
            <Json value={pack.expected_schema} label="Expected schema" />
          </Section>
        )}
        <Section title="Versions" id="versions">
          <ul>
            {ds.versions.map((v) => (
              <li key={v.id}>
                <Link to={`/datasets/${v.id}`}>v{v.version}</Link> · {v.case_count} cases{v.reason ? ` · ${v.reason}` : ''}
                {v.id === ds.id ? ' (shown)' : ''}
              </li>
            ))}
          </ul>
        </Section>
      </Content>
      <SplitDialog dataset={ds} open={splitting} onOpenChange={setSplitting} />
    </>
  )
}
