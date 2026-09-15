import { useMutation } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatDate } from '../api/format'
import { useScenario } from '../api/hooks'
import type { ValidationReport } from '../api/types'
import { Json } from '../components/Content'
import { ActionError, Hash, KeyValue } from '../components/Misc'
import { Content, PageHeader, Section } from '../components/Page'
import { ErrorState, Loading } from '../components/States'
import { Badge } from '../components/Status'
import { ValidationList } from './ScenarioWizardPage'

export function ScenarioDetailPage() {
  const { id } = useParams()
  const scenario = useScenario(id)
  const validate = useMutation({
    mutationFn: () => api.post<ValidationReport>('/scenarios/validate', { document: scenario.data?.definition }),
  })

  if (scenario.isPending)
    return (
      <>
        <PageHeader title="Scenario" />
        <Content>
          <Loading />
        </Content>
      </>
    )
  if (scenario.isError)
    return (
      <>
        <PageHeader title="Scenario" />
        <Content>
          <ErrorState error={scenario.error} onRetry={() => void scenario.refetch()} />
        </Content>
      </>
    )
  const s = scenario.data
  const d = s.definition
  const mandatory = new Set(s.datasets[0]?.pass_rule.mandatory_graders ?? [])
  return (
    <>
      <PageHeader
        title={`${s.name} · v${s.version}`}
        subtitle={`${s.pack.replace(/_/g, ' ')}${s.is_demo ? ' · demo' : ''}`}
        actions={
          <>
            <button type="button" className="btn" onClick={() => validate.mutate()} disabled={validate.isPending}>
              Validate
            </button>
            <Link className="btn" to={`/scenarios/new?clone=${s.id}`}>
              Clone
            </Link>
            <Link className="btn" to={`/scenarios/new?from=${s.id}`}>
              Edit as new version
            </Link>
            <Link className="btn btn-primary" to={`/runs/new?scenario=${s.id}`}>
              Run
            </Link>
          </>
        }
      />
      <Content>
        <ActionError error={validate.error} />
        {validate.data && <ValidationList report={validate.data.data} />}
        <Section title="Task contract" id="contract">
          <p>{s.contract}</p>
          {d.description && <p className="muted small">{d.description}</p>}
          <KeyValue
            items={[
              ['Slices', s.slice_keys.join(', ') || '—'],
              ['Critical invariants', s.critical_invariants.join(', ') || '—'],
              ['Allowed labels', d.allowed_labels?.join(', ') || '—'],
              ['Event definition', d.event_definition ?? '—'],
              ['Hash', <Hash key="h" value={s.hash} />],
              ['Created', formatDate(s.created_at)],
              ['Reason', s.reason || '—'],
            ]}
          />
        </Section>
        <Section title="Graders" id="graders">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Grader</th>
                  <th>Kind</th>
                  <th>Version</th>
                  <th>Checks / rubric</th>
                  <th>Pass rule</th>
                </tr>
              </thead>
              <tbody>
                {s.graders.map((g) => (
                  <tr key={g.id}>
                    <td>{g.name}</td>
                    <td>{g.kind}</td>
                    <td className="num">v{g.version}</td>
                    <td className="small">
                      {Array.isArray(g.config.checks) ? (g.config.checks as string[]).join(', ') : g.rubric || '—'}
                    </td>
                    <td>{mandatory.has(g.name) ? <Badge tone="info">mandatory</Badge> : <Badge tone="na">optional</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            A trial passes only when every applicable mandatory grader passes. Optional graders are reported but can neither veto nor
            satisfy a pass.
          </p>
        </Section>
        <Section title="Datasets" id="datasets">
          {s.datasets.length === 0 ? (
            <p className="muted">
              No datasets yet. <Link to="/datasets?import=1">Import cases</Link> for this scenario.
            </p>
          ) : (
            <ul>
              {s.datasets.map((ds) => (
                <li key={ds.id}>
                  <Link to={`/datasets/${ds.id}`}>
                    {ds.name} v{ds.version}
                  </Link>{' '}
                  · {ds.case_count} cases
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Versions" id="versions">
          <ul>
            {s.versions.map((v) => (
              <li key={v.id}>
                <Link to={`/scenarios/${v.id}`}>v{v.version}</Link> · {formatDate(v.created_at)}
                {v.reason ? ` · ${v.reason}` : ''}
                {v.id === s.id ? ' (shown)' : ''}
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Definition" id="definition">
          <Json value={d} label="Scenario definition" />
        </Section>
      </Content>
    </>
  )
}
