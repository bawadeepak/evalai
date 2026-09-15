import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile } from '../api/client'
import { formatBytes, formatDate } from '../api/format'
import { useExports, useHealth, useSettings } from '../api/hooks'
import type { ExportRecord, ImportRecord } from '../api/types'
import { useProject } from '../app/project'
import { getReviewer, setReviewer } from '../app/storage'
import { Json } from '../components/Content'
import { ActionError, KeyValue } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { QueryState } from '../components/States'
import { Badge, StatusBadge } from '../components/Status'
import { useToast } from '../components/Toast'

function ReviewerSetting() {
  const [name, setName] = useState(getReviewer)
  const [saved, setSaved] = useState(false)
  return (
    <Section title="Reviewer" id="reviewer">
      <form
        className="row"
        style={{ alignItems: 'flex-end' }}
        onSubmit={(e) => {
          e.preventDefault()
          setReviewer(name)
          setSaved(true)
        }}
      >
        <Field id="reviewer-name" label="Reviewer name" hint="Stored in this browser only and sent with each review you record.">
          {(props) => (
            <input
              {...props}
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setSaved(false)
              }}
            />
          )}
        </Field>
        <button type="submit" className="btn">
          Save
        </button>
        {saved && (
          <span className="small muted" role="status">
            Saved
          </span>
        )}
      </form>
    </Section>
  )
}

function ExportImport() {
  const { projectId, setProjectId } = useProject()
  const exports = useExports(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [redact, setRedact] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [importId, setImportId] = useState<string | null>(null)
  const [importState, setImportState] = useState<ImportRecord | null>(null)

  const createExport = useMutation({
    mutationFn: () => api.post<ExportRecord>('/exports', { project_id: projectId, redact_text: redact }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['exports'] }),
  })
  const validate = useMutation({
    mutationFn: (f: File) => api.upload<{ ok: boolean; source: Record<string, unknown>; counts: Record<string, number> }>('/imports/validate', f),
  })
  const startImport = useMutation({
    mutationFn: (f: File) => api.upload<{ id: string; status: string }>('/imports', f, { name: name || undefined }),
    onSuccess: ({ data }) => {
      setImportId(data.id)
      void poll(data.id)
    },
  })

  async function poll(id: string) {
    for (let i = 0; i < 120; i++) {
      const { data } = await api.get<ImportRecord>(`/imports/${id}`)
      setImportState(data)
      if (!['queued', 'running'].includes(data.status)) {
        if (data.project_id) {
          void queryClient.invalidateQueries({ queryKey: ['projects'] })
          toast('Import finished as a new project.')
        }
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }

  return (
    <Section title="Export and import" id="exchange">
      <div className="grid grid-2">
        <div className="stack">
          <h3>Export this project</h3>
          <p className="small muted">
            A ZIP with a manifest and checksums. Credentials are never exported; optional redaction masks free text and records a
            redaction manifest.
          </p>
          <label className="checkbox">
            <input type="checkbox" checked={redact} onChange={(e) => setRedact(e.target.checked)} />
            Redact free text (inputs and outputs)
          </label>
          <div>
            <button type="button" className="btn" onClick={() => createExport.mutate()} disabled={!projectId || createExport.isPending}>
              Create export
            </button>
          </div>
          <ActionError error={createExport.error} />
          <QueryState query={exports}>
            {(rows) =>
              rows.length === 0 ? (
                <p className="small muted">No exports yet.</p>
              ) : (
                <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }} data-testid="exports">
                  {rows.map((row) => (
                    <li key={row.id} className="row-between">
                      <span className="small">
                        {formatDate(row.created_at)} · {row.status}
                        {row.options.redact_text ? ' · redacted' : ''}
                      </span>
                      {row.download_url && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => void downloadFile(`/exports/${row.id}/download`, `eval-triage-export-${row.id.slice(0, 8)}.zip`)}
                        >
                          Download
                        </button>
                      )}
                      {row.error && <span className="small" style={{ color: 'var(--danger)' }}>{String(row.error.message ?? 'failed')}</span>}
                    </li>
                  ))}
                </ul>
              )
            }
          </QueryState>
        </div>
        <div className="stack">
          <h3>Import a project archive</h3>
          <p className="small muted">
            The archive is validated first (paths, checksums, sizes; no code or YAML objects). It is imported as a new project and
            never overwrites existing data. URLs inside it are never called.
          </p>
          <Field id="import-file" label="Archive (.zip)">
            {(props) => (
              <input
                {...props}
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => {
                  const next = e.target.files?.[0] ?? null
                  setFile(next)
                  setImportId(null)
                  setImportState(null)
                  if (next) validate.mutate(next)
                }}
              />
            )}
          </Field>
          <ActionError error={validate.error} title="The archive failed validation" />
          {validate.data && (
            <div className="notice ok" role="status">
              <div className="stack" style={{ gap: 2 }}>
                <strong>Archive is valid</strong>
                <span className="small">
                  Source project: {String(validate.data.data.source.name ?? 'unknown')} ·{' '}
                  {Object.entries(validate.data.data.counts)
                    .map(([k, v]) => `${v} ${k}`)
                    .join(', ')}
                </span>
              </div>
            </div>
          )}
          <Field id="import-name" label="Name for the imported project (optional)">
            {(props) => <input {...props} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <div>
            <button type="button" className="btn" disabled={!file || !validate.data || startImport.isPending} onClick={() => file && startImport.mutate(file)}>
              Import as new project
            </button>
          </div>
          <ActionError error={startImport.error} />
          {importId && importState && (
            <div className="notice info" role="status" data-testid="import-status">
              <div className="stack" style={{ gap: 4 }}>
                <span>Import {importState.status}</span>
                {importState.project_id && (
                  <button type="button" className="btn btn-sm" onClick={() => setProjectId(importState.project_id!)}>
                    Switch to the imported project
                  </button>
                )}
                {importState.error && <span>{String(importState.error.message ?? '')}</span>}
              </div>
            </div>
          )}
        </div>
      </div>
    </Section>
  )
}

export function SettingsPage() {
  const settings = useSettings()
  const health = useHealth()
  return (
    <>
      <PageHeader title="Settings" subtitle="Local paths, workers, limits, plugins and retention" />
      <Content>
        <ReviewerSetting />
        <QueryState query={settings}>
          {(s) => (
            <>
              <div className="grid grid-2">
                <Section title="Storage" id="paths">
                  <KeyValue items={Object.entries(s.paths).map(([k, v]) => [k.replace(/_/g, ' '), <code key={k}>{v}</code>])} />
                </Section>
                <Section title="Service and worker" id="worker">
                  <KeyValue
                    items={[
                      ['API', `${s.api.host}:${s.api.port}${s.api.loopback_only ? ' (loopback only)' : ''}`],
                      ['Worker', <StatusBadge key="w" kind="run" value={s.worker.status === 'ok' ? 'running' : 'failed'} title={s.worker.status} />],
                      ['Live workers', s.worker.live_workers],
                      ['Last heartbeat', formatDate(s.worker.last_heartbeat)],
                      ['Lease / heartbeat', `${s.worker.lease_seconds} s / ${s.worker.heartbeat_seconds} s`],
                      ['Slots', s.worker.slots],
                    ]}
                  />
                </Section>
                <Section title="Limits" id="limits">
                  <KeyValue items={Object.entries(s.limits).map(([k, v]) => [k.replace(/_/g, ' '), v])} />
                </Section>
                <Section title="Redaction and retention" id="retention">
                  <KeyValue
                    items={[
                      ['Redaction', `${s.redaction.version}: ${s.redaction.policy}`],
                      ['Retention', s.retention.policy],
                      ['Orphans', Object.entries(s.retention.orphans).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ')],
                    ]}
                  />
                </Section>
              </div>
              <Section title="Plugins" id="plugins">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Plugin</th>
                        <th>Status</th>
                        <th>Purpose</th>
                        <th>How to enable</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(s.plugins).map(([name, plugin]) => (
                        <tr key={name}>
                          <td>{name}</td>
                          <td>{plugin.available ? <Badge tone="ok">✓ Available</Badge> : <Badge tone="na">– Unavailable</Badge>}</td>
                          <td className="small">{plugin.purpose}</td>
                          <td className="small">
                            <code>{plugin.install}</code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
              <Section title="MemoryAI" id="memoryai">
                <KeyValue
                  items={[
                    ['Source', <code key="s">{s.memoryai.source_path}</code>],
                    ['Interpreter', <code key="p">{s.memoryai.python}</code>],
                    ['Available', `${s.memoryai.source_available ? 'source found' : 'source missing'} · ${s.memoryai.python_available ? 'interpreter found' : 'interpreter missing'}`],
                    ['Isolated stores on disk', formatBytes(s.memoryai.stores_dir_bytes)],
                    ['Stores recorded', Object.entries(s.memoryai.isolated_stores).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'],
                    ['Clean-up', s.memoryai.cleanup],
                  ]}
                />
              </Section>
              <Section title="Pricing table" id="pricing">
                <p className="small muted">{s.pricing.sources.map((src) => `${src.as_of}: ${src.description}`).join(' ')}</p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Adapter</th>
                        <th>Model</th>
                        <th className="num">Input / 1M</th>
                        <th className="num">Output / 1M</th>
                        <th>As of</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.pricing.entries.map((entry, i) => (
                        <tr key={i}>
                          <td>{String(entry.adapter)}</td>
                          <td>{String(entry.model)}</td>
                          <td className="num">
                            {String(entry.input_per_million)} {String(entry.currency ?? '')}
                          </td>
                          <td className="num">
                            {String(entry.output_per_million)} {String(entry.currency ?? '')}
                          </td>
                          <td>{String(entry.as_of ?? '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            </>
          )}
        </QueryState>
        <ExportImport />
        <Section title="Health diagnostics" id="diagnostics">
          <QueryState query={health}>{(h) => <Json value={h} label="Health response" />}</QueryState>
        </Section>
      </Content>
    </>
  )
}
