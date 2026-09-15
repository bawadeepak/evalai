// Optional integrations: plugin capabilities, result-file imports (Promptfoo,
// Inspect) and explicitly configured runs. Upstream verdicts and scores are
// shown as reported; they are never re-graded or read as probabilities.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { formatDate } from '../../api/format'
import { useExternalImports, useIntegrations, useJob } from '../../api/hooks'
import type { ExternalImport, IntegrationPlugin } from '../../api/types'
import { useProject } from '../../app/project'
import { ActionError, readFileText } from '../../components/Misc'
import { Field, Section } from '../../components/Page'
import { QueryState } from '../../components/States'
import { Badge } from '../../components/Status'

function Capability({ name, value }: { name: string; value: IntegrationPlugin['capabilities'][string] }) {
  return (
    <span className="row small" style={{ gap: 4 }} title={value.reason ?? undefined}>
      {value.available ? <Badge tone="ok">✓ {name}</Badge> : <Badge tone="na">– {name} unavailable</Badge>}
      {!value.available && value.reason && <span className="tiny muted">{value.reason}</span>}
    </span>
  )
}

function JobResult({ jobId }: { jobId: string }) {
  const job = useJob(jobId)
  if (!job.data || ['queued', 'running'].includes(job.data.status)) return <p className="small muted">Running…</p>
  const result = job.data.result as { ok?: boolean; error?: string; import_id?: string } | null
  if (result?.ok && result.import_id)
    return (
      <p className="notice ok small" role="status">
        Finished. <Link to={`/external/${result.import_id}`}>View imported results</Link>
      </p>
    )
  return (
    <p className="notice bad small" role="alert">
      Not completed: {result?.error ?? job.data.status}
    </p>
  )
}

function RunForms({ plugins }: { plugins: IntegrationPlugin[] }) {
  const { projectId } = useProject()
  const [config, setConfig] = useState('')
  const [task, setTask] = useState('')
  const [model, setModel] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: (body: { path: string; payload: Record<string, unknown> }) => api.post<{ job_id: string }>(body.path, { project_id: projectId, ...body.payload }),
    onSuccess: ({ data }) => setJobId(data.job_id),
  })
  const promptfoo = plugins.find((p) => p.id === 'promptfoo')
  const inspect = plugins.find((p) => p.id === 'inspect')
  const promptfooRun = promptfoo?.capabilities.run
  const inspectRun = inspect?.capabilities.run
  if (!promptfooRun?.available && !inspectRun?.available) {
    return (
      <p className="small muted">
        Running suites is off: Promptfoo needs <code>EVAL_TRIAGE_PROMPTFOO_COMMAND</code> and <code>EVAL_TRIAGE_PROMPTFOO_WORKDIR</code>; Inspect
        needs the optional <code>inspect_ai</code> package. Importing result files works without either.
      </p>
    )
  }
  return (
    <div className="stack-lg">
      {promptfooRun?.available && (
        <form
          className="row"
          style={{ alignItems: 'flex-end' }}
          onSubmit={(e) => {
            e.preventDefault()
            start.mutate({ path: '/integrations/promptfoo/runs', payload: { config } })
          }}
        >
          <Field id="pf-config" label="Promptfoo suite config (inside the configured working directory)">
            {(props) => <input {...props} value={config} onChange={(e) => setConfig(e.target.value)} placeholder="security/promptfooconfig.yaml" />}
          </Field>
          <button type="submit" className="btn" disabled={!config || start.isPending}>
            Run suite
          </button>
        </form>
      )}
      {inspectRun?.available && (
        <form
          className="row"
          style={{ alignItems: 'flex-end' }}
          onSubmit={(e) => {
            e.preventDefault()
            start.mutate({ path: '/integrations/inspect/runs', payload: { task, model } })
          }}
        >
          <Field id="inspect-task" label="Inspect task">
            {(props) => <input {...props} value={task} onChange={(e) => setTask(e.target.value)} />}
          </Field>
          <Field id="inspect-model" label="Model" hint="This makes model calls.">
            {(props) => <input {...props} value={model} onChange={(e) => setModel(e.target.value)} />}
          </Field>
          <button type="submit" className="btn" disabled={!task || !model || start.isPending}>
            Run task
          </button>
        </form>
      )}
      <ActionError error={start.error} />
      {jobId && <JobResult jobId={jobId} />}
    </div>
  )
}

function counts(row: ExternalImport): string {
  const s = row.summary as Record<string, number>
  return ['pass', 'fail', 'error', 'unscored'].filter((k) => s[k]).map((k) => `${s[k]} ${k}`).join(' · ') || 'no results'
}

export function ExternalResults() {
  const { projectId } = useProject()
  const plugins = useIntegrations()
  const imports = useExternalImports(projectId)
  const [plugin, setPlugin] = useState('promptfoo')
  const [file, setFile] = useState<File | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a file first')
      const content = await readFileText(file, 50 * 1024 * 1024)
      return api.post<ExternalImport>(`/integrations/${plugin}/imports`, { project_id: projectId, filename: file.name, content })
    },
    onSuccess: ({ data }) => {
      void queryClient.invalidateQueries({ queryKey: ['external-imports'] })
      navigate(`/external/${data.id}`)
    },
  })
  const uploadError = upload.error instanceof ApiError ? upload.error : upload.error

  return (
    <Section title="External results" id="external">
      <div className="stack-lg">
        <QueryState query={plugins}>
          {(list) => (
            <div className="grid grid-3" data-testid="integrations">
              {list.map((p) => (
                <article key={p.id} className="card card-muted stack">
                  <strong>
                    {p.title} <span className="tiny muted">{p.version}</span>
                  </strong>
                  <span className="small muted">{p.purpose}</span>
                  <span className="tiny muted">Packs: {p.supported_packs.join(', ')}</span>
                  <div className="stack" style={{ gap: 4 }}>
                    {Object.entries(p.capabilities).map(([name, value]) => (
                      <Capability key={name} name={name} value={value} />
                    ))}
                  </div>
                </article>
              ))}
            </div>
          )}
        </QueryState>

        <div className="stack">
          <h3>Import a result file</h3>
          <p className="small muted">
            Promptfoo <code>results.json</code> or an Inspect JSON log. Upstream identifiers, assertion types, statuses, reasons and errors are
            kept; the original file is stored (redacted if it contains secret-like values). Scores stay the tool’s own and are never read as
            probabilities.
          </p>
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <Field id="external-plugin" label="Format">
              {(props) => (
                <select {...props} value={plugin} onChange={(e) => setPlugin(e.target.value)}>
                  <option value="promptfoo">Promptfoo results (JSON)</option>
                  <option value="inspect">Inspect eval log (JSON)</option>
                </select>
              )}
            </Field>
            <Field id="external-file" label="File">
              {(props) => <input {...props} type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
            </Field>
            <button type="button" className="btn btn-primary" disabled={!file || !projectId || upload.isPending} onClick={() => upload.mutate()}>
              Import results
            </button>
          </div>
          <ActionError error={uploadError} title="Import refused" />
        </div>

        <div className="stack">
          <h3>Run configured tools</h3>
          {plugins.data ? <RunForms plugins={plugins.data} /> : null}
        </div>

        <div className="stack">
          <h3>Imported results</h3>
          <QueryState query={imports}>
            {(rows) =>
              rows.length === 0 ? (
                <p className="small muted">Nothing imported yet.</p>
              ) : (
                <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }} data-testid="external-imports">
                  {rows.map((row) => (
                    <li key={row.id} className="row-between">
                      <span className="row">
                        <Badge tone="info">{row.plugin}</Badge>
                        <Link to={`/external/${row.id}`}>{row.filename ?? row.id.slice(0, 8)}</Link>
                        <span className="small muted">{counts(row)}</span>
                      </span>
                      <span className="small muted">{formatDate(row.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )
            }
          </QueryState>
        </div>
      </div>
    </Section>
  )
}
