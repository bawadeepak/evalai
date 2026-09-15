import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fieldErrors } from '../api/client'
import { formatDate } from '../api/format'
import { useAdapters, useConnectionTest, useTargets } from '../api/hooks'
import type { AdapterInfo, ConnectionTest, TargetConfig } from '../api/types'
import { useProject } from '../app/project'
import { Json } from '../components/Content'
import { ActionError, Hash, KeyValue } from '../components/Misc'
import { Content, Field, PageHeader, parseJsonArray, parseJsonObject, Section } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { Badge, StatusBadge } from '../components/Status'
import { useToast } from '../components/Toast'

const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/

/** Heuristic: the user pasted a key instead of the name of an environment variable. */
export function looksLikeSecret(value: string): boolean {
  return /^(sk-|sk_|pk-|xox|ghp_|AIza)/.test(value) || (/[a-z]/.test(value) && /\d/.test(value) && value.length > 24) || value.includes('-')
}

export function credentialRefError(value: string): string | null {
  if (!value) return null
  if (looksLikeSecret(value)) return 'This looks like a secret value. Enter the NAME of an environment variable (e.g. OPENAI_API_KEY), never the key.'
  if (!ENV_NAME.test(value)) return 'Use an environment variable name: letters, digits and underscores.'
  return null
}

type FormState = {
  adapter: string
  name: string
  endpoint_type: string
  model: string
  base_url: string
  credential_ref: string
  parameters: string
  prompt_template: string
  tools: string
  memory_config: string
  experimental: boolean
}

function initialForm(base: TargetConfig | null, adapters: AdapterInfo[], copy: boolean): FormState {
  if (base) {
    return {
      adapter: base.adapter,
      name: copy ? `${base.name} (copy)` : base.name,
      endpoint_type: base.endpoint_type,
      model: base.model,
      base_url: base.base_url ?? '',
      credential_ref: base.credential_ref ?? '',
      parameters: Object.keys(base.parameters).length ? JSON.stringify(base.parameters, null, 2) : '',
      prompt_template: base.prompt_template,
      tools: base.tools.length ? JSON.stringify(base.tools, null, 2) : '',
      memory_config: Object.keys(base.memory_config).length ? JSON.stringify(base.memory_config, null, 2) : '',
      experimental: base.experimental,
    }
  }
  const first = adapters[0]
  return {
    adapter: first?.name ?? 'demo',
    name: '',
    endpoint_type: first?.endpoint_types[0] ?? '',
    model: '',
    base_url: '',
    credential_ref: first?.credential_default ?? '',
    parameters: '',
    prompt_template: '',
    tools: '',
    memory_config: '',
    experimental: false,
  }
}

function ProviderForm({
  mode,
  base,
  adapters,
  onDone,
}: {
  mode: 'new' | 'edit' | 'copy'
  base: TargetConfig | null
  adapters: AdapterInfo[]
  onDone: (config: TargetConfig | null) => void
}) {
  const { projectId } = useProject()
  const [form, setForm] = useState<FormState>(() => initialForm(base, adapters, mode === 'copy'))
  const [local, setLocal] = useState<Record<string, string>>({})
  const queryClient = useQueryClient()
  const adapter = adapters.find((a) => a.name === form.adapter)
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<TargetConfig>('/target-configs', body),
    onSuccess: ({ data }) => {
      void queryClient.invalidateQueries({ queryKey: ['targets'] })
      onDone(data)
    },
  })
  const server = fieldErrors(save.error)
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }))

  function submit() {
    const errors: Record<string, string> = {}
    if (!form.name.trim()) errors.name = 'A name is required'
    const credential = credentialRefError(form.credential_ref.trim())
    if (credential) errors.credential_ref = credential
    const parameters = parseJsonObject(form.parameters, 'Parameters')
    const tools = parseJsonArray(form.tools, 'Tools')
    const memory = parseJsonObject(form.memory_config, 'Memory configuration')
    if (parameters.error) errors.parameters = parameters.error
    if (tools.error) errors.tools = tools.error
    if (memory.error) errors.memory_config = memory.error
    setLocal(errors)
    if (Object.keys(errors).length) return
    save.mutate({
      project_id: projectId,
      name: form.name.trim(),
      adapter: form.adapter,
      endpoint_type: form.endpoint_type,
      model: form.model.trim(),
      base_url: form.base_url.trim() || null,
      credential_ref: form.credential_ref.trim() || null,
      parameters: parameters.value,
      prompt_template: form.prompt_template,
      tools: tools.value,
      memory_config: memory.value,
      experimental: form.experimental,
      parent_id: mode === 'edit' && base ? base.id : null,
    })
  }

  const error = (key: string) => local[key] ?? server[key] ?? null
  return (
    <Section title={mode === 'edit' ? `Edit “${base?.name}” as a new version` : mode === 'copy' ? 'Copy configuration' : 'Add a provider configuration'} id="provider-form">
      <form
        className="stack-lg"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
        noValidate
      >
        {mode === 'edit' && (
          <p className="notice info small">Saving creates version {base ? base.version + 1 : 2}. Earlier versions and the runs that used them are unchanged.</p>
        )}
        <div className="field-row">
          <Field id="pf-adapter" label="Adapter" hint={adapter?.description}>
            {(props) => (
              <select
                {...props}
                value={form.adapter}
                disabled={mode === 'edit'}
                onChange={(e) => {
                  const next = adapters.find((a) => a.name === e.target.value)
                  setForm((f) => ({
                    ...f,
                    adapter: e.target.value,
                    endpoint_type: next?.endpoint_types[0] ?? '',
                    credential_ref: next?.credential_default ?? '',
                  }))
                }}
              >
                {adapters.map((a) => (
                  <option key={a.name} value={a.name}>
                    {a.title}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field id="pf-name" label="Name" error={error('name')}>
            {(props) => <input {...props} value={form.name} onChange={(e) => set('name', e.target.value)} />}
          </Field>
          <Field id="pf-endpoint" label="Endpoint mode">
            {(props) => (
              <select {...props} value={form.endpoint_type} onChange={(e) => set('endpoint_type', e.target.value)}>
                {(adapter?.endpoint_types ?? []).map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field id="pf-model" label="Model" hint="The exact model name. Eval Triage never invents a default." error={error('model')}>
            {(props) => <input {...props} value={form.model} onChange={(e) => set('model', e.target.value)} />}
          </Field>
          {(form.adapter === 'openai_compatible' || form.adapter === 'openai') && (
            <Field id="pf-base-url" label="Base URL" hint={form.adapter === 'openai_compatible' ? 'e.g. http://127.0.0.1:11434/v1 for a local runner' : 'Optional override'} error={error('base_url')}>
              {(props) => <input {...props} value={form.base_url} onChange={(e) => set('base_url', e.target.value)} />}
            </Field>
          )}
          <Field
            id="pf-credential"
            label="Credential reference"
            hint="Name of an environment variable that holds the key. The key itself is never entered, stored or shown."
            error={error('credential_ref')}
          >
            {(props) => <input {...props} value={form.credential_ref} autoComplete="off" spellCheck={false} onChange={(e) => set('credential_ref', e.target.value)} />}
          </Field>
        </div>
        <Field
          id="pf-parameters"
          label="Parameters (JSON object)"
          hint={`Checked against the model's capabilities during run validation; unsupported parameters block the run. Capability-checked: ${Object.keys(adapter?.parameter_capabilities ?? {}).join(', ')}.`}
          error={error('parameters')}
        >
          {(props) => <textarea {...props} rows={4} value={form.parameters} placeholder='{"temperature": 0.2}' onChange={(e) => set('parameters', e.target.value)} />}
        </Field>
        <Field id="pf-prompt" label="Prompt template" hint="Optional. Case input is inserted by the scenario's pack.">
          {(props) => <textarea {...props} rows={3} value={form.prompt_template} onChange={(e) => set('prompt_template', e.target.value)} />}
        </Field>
        <Field id="pf-tools" label="Tools (JSON array)" error={error('tools')}>
          {(props) => <textarea {...props} rows={3} value={form.tools} onChange={(e) => set('tools', e.target.value)} />}
        </Field>
        {form.adapter === 'memoryai' && (
          <Field
            id="pf-memory"
            label="MemoryAI configuration (JSON object)"
            hint='{"backend": "real" | "fake", "llm_model": "gemma3:4b", "generation_target_config_id": "…"}. Models inside MemoryAI must be local; cloud providers are unsupported there.'
            error={error('memory_config')}
          >
            {(props) => <textarea {...props} rows={4} value={form.memory_config} onChange={(e) => set('memory_config', e.target.value)} />}
          </Field>
        )}
        <label className="checkbox">
          <input type="checkbox" checked={form.experimental} onChange={(e) => set('experimental', e.target.checked)} />
          <span>
            Experimental mode: allow capabilities marked “unknown” without a probe. Recorded as a warning in every run manifest.
          </span>
        </label>
        <ActionError error={save.error} title="The configuration was not saved" />
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {mode === 'edit' ? 'Save new version' : 'Save configuration'}
          </button>
          <button type="button" className="btn" onClick={() => onDone(null)}>
            Cancel
          </button>
        </div>
      </form>
    </Section>
  )
}

function ConnectionTestPanel({ config }: { config: TargetConfig }) {
  const [testId, setTestId] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: () => api.post<ConnectionTest>(`/target-configs/${config.id}/connection-tests`),
    onSuccess: ({ data }) => setTestId(data.id),
  })
  const test = useConnectionTest(testId)
  return (
    <div className="stack">
      <div className="row">
        <button type="button" className="btn" onClick={() => start.mutate()} disabled={start.isPending || (!!test.data && ['queued', 'running'].includes(test.data.status))}>
          Run connection test
        </button>
        <span className="small muted">Sends one small, bounded request to this endpoint{config.adapter === 'demo' ? ' (the demo adapter makes no network call)' : ''}. Needs a running worker.</span>
      </div>
      <ActionError error={start.error} />
      {test.data && (
        <div className="stack" data-testid="connection-test">
          <span>
            Status: <Badge tone={test.data.status === 'succeeded' ? 'ok' : test.data.status === 'failed' ? 'bad' : 'info'}>{test.data.status}</Badge>
          </span>
          {test.data.result && <Json value={test.data.result} label="Connection test result" />}
        </div>
      )}
    </div>
  )
}

function ConfigDetail({ config, versions }: { config: TargetConfig; versions: TargetConfig[] }) {
  const caps = Object.entries(config.capabilities)
  return (
    <Section
      title={`${config.name} · v${config.version}`}
      id="provider-detail"
      actions={
        <>
          <Link className="btn btn-sm" to={`/providers?config=${config.id}&edit=1`}>
            Edit as new version
          </Link>
          <Link className="btn btn-sm" to={`/providers?config=${config.id}&copy=1`}>
            Copy
          </Link>
        </>
      }
    >
      <div className="stack-lg">
        <KeyValue
          items={[
            ['Adapter', `${config.adapter} (${config.adapter_version}) · ${config.endpoint_type.replace(/_/g, ' ')}`],
            ['Model', config.model || '—'],
            ['Base URL', config.base_url ?? '—'],
            [
              'Credential',
              config.credential_ref ? (
                <span className="row" key="c">
                  <code>{config.credential_ref}</code>
                  <StatusBadge kind="credential" value={config.credential_status} />
                </span>
              ) : (
                <StatusBadge key="c" kind="credential" value="not_required" />
              ),
            ],
            ['Experimental', config.experimental ? 'yes — unknown capabilities allowed' : 'no'],
            ['Hash', <Hash key="h" value={config.hash} />],
            ['Created', formatDate(config.created_at)],
          ]}
        />
        <div>
          <h3>Capabilities</h3>
          <p className="small muted">Each capability records its evidence source and when it was verified.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Capability</th>
                  <th>State</th>
                  <th>Source</th>
                  <th>Verified</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {caps.map(([name, cap]) => (
                  <tr key={name}>
                    <td>{name.replace(/_/g, ' ')}</td>
                    <td>
                      <StatusBadge kind="capability" value={cap.state} />
                    </td>
                    <td className="small">{cap.source}</td>
                    <td className="small nowrap">{cap.verified_at ? formatDate(cap.verified_at) : '—'}</td>
                    <td className="small">{cap.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="grid grid-2">
          <div className="stack">
            <h3>Parameters</h3>
            <Json value={config.parameters} label="Parameters" />
          </div>
          <div className="stack">
            <h3>{config.adapter === 'memoryai' ? 'MemoryAI configuration' : 'Tools'}</h3>
            <Json value={config.adapter === 'memoryai' ? config.memory_config : config.tools} label="Configuration" />
          </div>
        </div>
        {config.prompt_template && (
          <div className="stack">
            <h3>Prompt template</h3>
            <pre className="box">{config.prompt_template}</pre>
          </div>
        )}
        <ConnectionTestPanel config={config} />
        {versions.length > 1 && (
          <div className="stack">
            <h3>Versions</h3>
            <ul>
              {versions.map((v) => (
                <li key={v.id}>
                  <Link to={`/providers?config=${v.id}`}>v{v.version}</Link> · {formatDate(v.created_at)}
                  {v.id === config.id ? ' (shown)' : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Section>
  )
}

export function ProvidersPage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const targets = useTargets(projectId)
  const adapters = useAdapters()
  const toast = useToast()
  const selectedId = params.get('config')
  const mode: 'new' | 'edit' | 'copy' | null = params.get('new') ? 'new' : params.get('edit') ? 'edit' : params.get('copy') ? 'copy' : null

  const groups = useMemo(() => {
    const byLogical = new Map<string, TargetConfig[]>()
    for (const config of targets.data ?? []) {
      byLogical.set(config.logical_id, [...(byLogical.get(config.logical_id) ?? []), config])
    }
    return [...byLogical.values()].map((versions) => versions.sort((a, b) => b.version - a.version))
  }, [targets.data])

  const selected = targets.data?.find((c) => c.id === selectedId) ?? null
  const selectedVersions = selected ? groups.find((g) => g[0]?.logical_id === selected.logical_id) ?? [] : []

  const go = (next: Record<string, string>) => setParams(new URLSearchParams(next))

  return (
    <>
      <PageHeader
        title="Providers"
        subtitle="Versioned target configurations. Secrets are referenced by environment variable name and never returned."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => go({ new: '1' })}>
            Add provider
          </button>
        }
      />
      <Content>
        {targets.isPending || adapters.isPending ? (
          <Loading />
        ) : targets.isError ? (
          <ErrorState error={targets.error} onRetry={() => void targets.refetch()} />
        ) : adapters.isError ? (
          <ErrorState error={adapters.error} onRetry={() => void adapters.refetch()} />
        ) : (
          <>
            {mode && (
              <ProviderForm
                key={`${mode}-${selectedId ?? ''}`}
                mode={mode}
                base={mode === 'new' ? null : selected}
                adapters={adapters.data ?? []}
                onDone={(config) => {
                  if (config) {
                    toast(`Saved ${config.name} v${config.version}`)
                    go({ config: config.id })
                  } else go(selectedId ? { config: selectedId } : {})
                }}
              />
            )}
            {groups.length === 0 ? (
              <Empty title="No provider configurations" action={<button type="button" className="btn" onClick={() => go({ new: '1' })}>Add provider</button>}>
                The demo adapter runs offline with synthetic outputs. OpenAI, Anthropic and local OpenAI-compatible runners need a model
                name and, for cloud providers, a credential reference.
              </Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Adapter</th>
                      <th>Model</th>
                      <th>Credential</th>
                      <th className="num">Version</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((versions) => {
                      const latest = versions[0]!
                      return (
                        <tr key={latest.logical_id} className={selected?.logical_id === latest.logical_id ? 'selected' : undefined}>
                          <td>
                            <Link to={`/providers?config=${latest.id}`}>{latest.name}</Link>
                            {latest.is_demo && <span className="tiny muted"> · demo</span>}
                          </td>
                          <td className="small">
                            {latest.adapter} · {latest.endpoint_type.replace(/_/g, ' ')}
                          </td>
                          <td className="small">{latest.model || '—'}</td>
                          <td>
                            {latest.credential_ref ? (
                              <span className="row" style={{ flexWrap: 'nowrap' }}>
                                <code className="tiny">{latest.credential_ref}</code>
                                <StatusBadge kind="credential" value={latest.credential_status} />
                              </span>
                            ) : (
                              <StatusBadge kind="credential" value="not_required" />
                            )}
                          </td>
                          <td className="num">
                            v{latest.version}
                            {versions.length > 1 ? ` (${versions.length})` : ''}
                          </td>
                          <td className="small nowrap">{formatDate(latest.created_at)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {selected && !mode && <ConfigDetail config={selected} versions={selectedVersions} />}
          </>
        )}
      </Content>
    </>
  )
}
