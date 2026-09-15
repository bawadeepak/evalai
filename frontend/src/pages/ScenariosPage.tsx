import { Link } from 'react-router-dom'
import { usePacks, useScenarios } from '../api/hooks'
import { useProject } from '../app/project'
import { Content, PageHeader, Section } from '../components/Page'
import { Empty, ErrorState, Loading } from '../components/States'
import { Badge } from '../components/Status'

export function ScenariosPage() {
  const { projectId } = useProject()
  const scenarios = useScenarios(projectId)
  const packs = usePacks()
  const counts = new Map<string, number>()
  for (const s of scenarios.data ?? []) counts.set(s.pack, (counts.get(s.pack) ?? 0) + 1)

  return (
    <>
      <PageHeader
        title="Scenarios"
        subtitle="A scenario is a versioned task contract with graders, invariants and slices."
        actions={
          <>
            <Link to="/datasets?import=1" className="btn">
              Import document
            </Link>
            <Link to="/scenarios/new" className="btn btn-primary">
              New scenario
            </Link>
          </>
        }
      />
      <Content>
        <Section title="Scenarios in this project" id="scenario-list">
          {scenarios.isPending ? (
            <Loading />
          ) : scenarios.isError ? (
            <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} />
          ) : (scenarios.data ?? []).length === 0 ? (
            <Empty title="No scenarios yet" action={<Link to="/scenarios/new" className="btn">Create a scenario</Link>}>
              Start from a pack below, or import a scenario document (JSON, JSONL or YAML).
            </Empty>
          ) : (
            <div className="grid grid-auto">
              {scenarios.data!.map((s) => (
                <article key={s.id} className="card stack" data-testid="scenario-card">
                  <div className="row-between">
                    <h3>
                      <Link to={`/scenarios/${s.id}`}>{s.name}</Link>
                    </h3>
                    <Badge tone="info">v{s.version}</Badge>
                  </div>
                  <span className="small muted">{s.pack.replace(/_/g, ' ')}</span>
                  <p className="small" style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {s.contract}
                  </p>
                  <span className="small muted">
                    {s.dataset_count ?? 0} dataset{s.dataset_count === 1 ? '' : 's'} · {s.case_count ?? 0} cases · {s.grader_refs.length} grader
                    {s.grader_refs.length === 1 ? '' : 's'}
                    {s.critical_invariants.length ? ` · ${s.critical_invariants.length} critical invariants` : ''}
                  </span>
                  <div className="row">
                    <Link className="btn btn-sm" to={`/runs/new?scenario=${s.id}`}>
                      Run
                    </Link>
                    <Link className="btn btn-sm" to={`/scenarios/new?from=${s.id}`}>
                      Edit as new version
                    </Link>
                    <Link className="btn btn-sm" to={`/scenarios/new?clone=${s.id}`}>
                      Clone
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </Section>
        <Section title="Evaluation packs" id="packs">
          {packs.isPending ? (
            <Loading />
          ) : packs.isError ? (
            <ErrorState error={packs.error} onRetry={() => void packs.refetch()} />
          ) : (
            <div className="grid grid-auto">
              {packs.data!.packs.map((p) => (
                <article key={p.pack} className="card card-muted stack">
                  <h3>{p.title}</h3>
                  <p className="small muted">{p.summary}</p>
                  <span className="tiny muted">
                    {counts.get(p.pack) ?? 0} scenario{counts.get(p.pack) === 1 ? '' : 's'}
                    {p.requires_episode ? ' · episode-based' : ''}
                  </span>
                  <div>
                    <Link className="btn btn-sm" to={`/scenarios/new?pack=${p.pack}`}>
                      Start from this pack
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </Section>
      </Content>
    </>
  )
}
