// Global shell: navigation, project selector, health footer, demo banner and
// the service-unreachable notice. Collapses to a menu below 768px.

import { Suspense, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useHealth } from '../api/hooks'
import { ApiError } from '../api/client'
import { Loading } from '../components/States'
import { useProject } from './project'
import { useTheme, type ThemeChoice } from './theme'

const LINKS: [string, string, string][] = [
  ['/', 'Overview', '⌂'],
  ['/scenarios', 'Scenarios', '◇'],
  ['/datasets', 'Datasets', '▤'],
  ['/runs', 'Runs', '▶'],
  ['/triage', 'Triage', '⚑'],
  ['/probability', 'Probability Lab', '∿'],
  ['/compare', 'Compare', '⇄'],
  ['/providers', 'Providers', '⚙'],
  ['/settings', 'Settings', '☰'],
]

function HealthFooter() {
  const health = useHealth()
  if (health.isError) {
    const disconnected = health.error instanceof ApiError && health.error.disconnected
    return (
      <div className="health-line" role="status">
        <span className="dot bad" aria-hidden="true" />
        {disconnected ? 'Service unreachable' : 'Health check failed'}
      </div>
    )
  }
  if (!health.data) return <div className="health-line muted">Checking service…</div>
  const { api, database, worker } = health.data
  const workerTone = worker.status === 'ok' ? 'ok' : worker.status === 'stale' ? 'warn' : 'bad'
  return (
    <div className="stack" style={{ gap: 4 }} aria-label="Service health" data-testid="health-footer">
      <div className="health-line">
        <span className={`dot ${api.status === 'ok' ? 'ok' : 'bad'}`} aria-hidden="true" />
        API {api.status === 'ok' ? 'running' : api.status} · v{api.version}
      </div>
      <div className="health-line">
        <span className={`dot ${database.status === 'ok' ? 'ok' : 'bad'}`} aria-hidden="true" />
        Database {database.status === 'ok' ? 'ok' : database.status}
      </div>
      <div className="health-line" data-testid="worker-status">
        <span className={`dot ${workerTone}`} aria-hidden="true" />
        Worker{' '}
        {worker.status === 'ok'
          ? `running (${worker.live_workers})`
          : worker.status === 'stale'
            ? 'not responding'
            : 'not started — runs stay queued'}
      </div>
    </div>
  )
}

function ProjectSelector() {
  const { projects, project, setProjectId, isPending } = useProject()
  if (isPending) return <div className="skeleton" style={{ height: 32 }} />
  if (!projects.length) return <p className="small muted">No projects yet</p>
  return (
    <div className="field">
      <label htmlFor="project-select" className="tiny muted">
        Project
      </label>
      <select id="project-select" value={project?.id ?? ''} onChange={(e) => setProjectId(e.target.value)}>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.is_demo ? ' (demo)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function ThemeSelect() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="field">
      <label htmlFor="theme-select" className="tiny muted">
        Theme
      </label>
      <select id="theme-select" value={theme} onChange={(e) => setTheme(e.target.value as ThemeChoice)}>
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </div>
  )
}

export function Shell() {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const { project } = useProject()
  const health = useHealth()
  const disconnected = health.isError && health.error instanceof ApiError && health.error.disconnected
  const openButton = useRef<HTMLButtonElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  useEffect(() => setNavOpen(false), [location.pathname])
  // On narrow screens the navigation is an overlay: focus moves into it when it
  // opens and back to the menu button when it closes; Escape closes it.
  useEffect(() => {
    if (navOpen) {
      closeButton.current?.focus()
      const onKey = (event: KeyboardEvent) => {
        if (event.key === 'Escape') setNavOpen(false)
      }
      window.addEventListener('keydown', onKey)
      wasOpen.current = true
      return () => window.removeEventListener('keydown', onKey)
    }
    if (wasOpen.current) {
      wasOpen.current = false
      openButton.current?.focus()
    }
    return undefined
  }, [navOpen])

  return (
    <div className={`shell${navOpen ? ' nav-open' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {navOpen && <div className="nav-backdrop" aria-hidden="true" onClick={() => setNavOpen(false)} />}
      <nav className="nav" aria-label="Primary">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ⌖
          </span>
          Eval Triage
          <button ref={closeButton} type="button" className="btn btn-sm nav-close" aria-label="Close navigation" onClick={() => setNavOpen(false)}>
            ×
          </button>
        </div>
        <ProjectSelector />
        <ul className="nav-links">
          {LINKS.map(([to, label, icon]) => (
            <li key={to}>
              <NavLink to={to} end={to === '/'} onClick={() => setNavOpen(false)}>
                <span className="nav-icon" aria-hidden="true">
                  {icon}
                </span>
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="nav-footer">
          <ThemeSelect />
          <HealthFooter />
        </div>
      </nav>
      <div className="main">
        <div className="topbar">
          <button
            ref={openButton}
            type="button"
            className="btn btn-sm"
            aria-expanded={navOpen}
            aria-label="Open navigation"
            onClick={() => setNavOpen(true)}
          >
            ☰ Menu
          </button>
          <strong>Eval Triage</strong>
          {project && <span className="muted small wrap-anywhere">{project.name}</span>}
        </div>
        {disconnected && (
          <div className="notice warn" role="status" style={{ borderRadius: 0 }} data-state="disconnected">
            Cannot reach the local service. Showing the last loaded data; reconnecting automatically.
          </div>
        )}
        {project?.is_demo && (
          <div className="demo-banner" role="note" data-testid="demo-banner">
            <strong>Demo project.</strong> Every result here comes from synthetic fixtures — nothing is a measurement of
            MemoryAI or of any model.
          </div>
        )}
        <main id="main" tabIndex={-1} style={{ outline: 'none' }}>
          <Suspense
            fallback={
              <div className="content">
                <Loading label="Loading page" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
