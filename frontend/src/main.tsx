import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

type Health = { data: { api: { status: string; version: string }; database: { status: string }; worker: { status: string } } }

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    fetch('/api/v1/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
  }, [])
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <h1>Eval Triage</h1>
      {error && <p role="alert">API unavailable: {error}</p>}
      {health && (
        <p>
          API {health.data.api.status} · database {health.data.database.status} · worker {health.data.worker.status}
        </p>
      )}
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
