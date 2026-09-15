import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, downloadFile, ApiError } from '../api/client'
import { formatDate } from '../api/format'
import { useDatasets, useScenarios } from '../api/hooks'
import type { Dataset, ValidationReport } from '../api/types'
import { useProject } from '../app/project'
import { ActionError, readFileText } from '../components/Misc'
import { Content, Field, PageHeader, Section } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { Badge } from '../components/Status'
import { useToast } from '../components/Toast'
import { ValidationList } from './ScenarioWizardPage'

export function splitSummary(ds: Dataset): string {
  return Object.entries(ds.split_manifest?.splits ?? {})
    .map(([split, v]) => `${split} ${v.cases} (${v.clusters} clusters)`)
    .join(' · ')
}

function ImportPanel({ onClose }: { onClose: () => void }) {
  const { projectId } = useProject()
  const scenarios = useScenarios(projectId)
  const [file, setFile] = useState<File | null>(null)
  const [scenarioId, setScenarioId] = useState('')
  const [name, setName] = useState('')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a file first')
      const content = await readFileText(file)
      return api.post<{ dataset: Dataset | null; scenario?: { id: string; name: string } }>('/imports/documents', {
        project_id: projectId,
        filename: file.name,
        content,
        scenario_id: scenarioId || null,
        dataset_name: name || null,
      })
    },
    onSuccess: ({ data }) => {
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      void queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      toast('Import saved as a new immutable version.')
      if (data.dataset) navigate(`/datasets/${data.dataset.id}`)
      else if (data.scenario) navigate(`/scenarios/${data.scenario.id}`)
    },
  })
  const report = upload.error instanceof ApiError && upload.error.details && typeof upload.error.details === 'object' && 'errors' in (upload.error.details as object)
    ? (upload.error.details as ValidationReport)
    : null

  return (
    <Section title="Import JSON, JSONL or YAML" id="import">
      <div className="stack-lg">
        <p className="small muted">
          A full scenario document (with <code>pack</code>) creates a scenario, graders and a dataset. A list of cases needs a target
          scenario. YAML is parsed safely (no objects or code). Every row and field error is listed.
        </p>
        <div className="field-row">
          <Field id="import-doc-file" label="File">
            {(props) => <input {...props} type="file" accept=".json,.jsonl,.yaml,.yml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
          </Field>
          <Field id="import-doc-scenario" label="Scenario (for case lists)">
            {(props) => (
              <select {...props} value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                <option value="">— document contains its scenario —</option>
                {(scenarios.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} v{s.version}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field id="import-doc-name" label="Dataset name (optional)">
            {(props) => <input {...props} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
        </div>
        {report ? <ValidationList report={report} /> : <ActionError error={upload.error} title="Import failed" />}
        <div className="row">
          <button type="button" className="btn btn-primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? 'Importing…' : 'Validate and import'}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </Section>
  )
}

export function DatasetsPage() {
  const { projectId } = useProject()
  const [params, setParams] = useSearchParams()
  const datasets = useDatasets(projectId)
  const scenarios = useScenarios(projectId, false)
  const scenarioName = new Map((scenarios.data ?? []).map((s) => [s.id, `${s.name} v${s.version}`]))
  const importing = params.get('import') === '1'

  return (
    <>
      <PageHeader
        title="Datasets"
        subtitle="Immutable dataset versions with cluster-aware splits and provenance."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setParams(new URLSearchParams({ import: '1' }))}>
            Import
          </button>
        }
      />
      <Content>
        {importing && <ImportPanel onClose={() => setParams(new URLSearchParams())} />}
        {datasets.isPending ? (
          <Loading />
        ) : datasets.isError ? (
          <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />
        ) : (datasets.data ?? []).length === 0 ? (
          <Empty title="No datasets yet" action={<button type="button" className="btn" onClick={() => setParams(new URLSearchParams({ import: '1' }))}>Import a dataset</button>}>
            Import cases, or create a scenario with initial cases.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Scenario</th>
                  <th className="num">Cases</th>
                  <th>Splits</th>
                  <th>Pass rule</th>
                  <th>Provenance</th>
                  <th>Created</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {datasets.data!.map((ds) => (
                  <tr key={ds.id}>
                    <td>
                      <Link to={`/datasets/${ds.id}`}>{ds.name}</Link> <Badge tone="info">v{ds.version}</Badge>
                      {ds.is_demo && <span className="tiny muted"> · demo</span>}
                    </td>
                    <td className="small">
                      <Link to={`/scenarios/${ds.scenario_id}`}>{scenarioName.get(ds.scenario_id) ?? ds.scenario_id.slice(0, 8)}</Link>
                    </td>
                    <td className="num">{ds.case_count}</td>
                    <td className="small">
                      {splitSummary(ds) || '—'}
                      {ds.split_manifest?.leaking_clusters?.length ? (
                        <div>
                          <Badge tone="warn">! {ds.split_manifest.leaking_clusters.length} clusters span splits</Badge>
                        </div>
                      ) : null}
                    </td>
                    <td className="small">{ds.pass_rule.mandatory_graders.join(', ')}</td>
                    <td className="small">{String(ds.provenance.source ?? '—')}</td>
                    <td className="small nowrap">{formatDate(ds.created_at)}</td>
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => void downloadFile(`/datasets/${ds.id}/export`, `${ds.name}-v${ds.version}.jsonl`, { format: 'jsonl' })}>
                        Export JSONL
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Content>
    </>
  )
}
