import { useEffect, type ReactNode } from 'react'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · Eval Triage`
  }, [title])
  return (
    <header className="page-header">
      <div className="stack" style={{ gap: 2 }}>
        <h1>{title}</h1>
        {subtitle && <div className="subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

export function Content({ children }: { children: ReactNode }) {
  return <div className="content">{children}</div>
}

export function Section({ title, actions, children, id }: { title: string; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="card" aria-labelledby={id ? `${id}-title` : undefined} id={id}>
      <div className="card-header">
        <h2 id={id ? `${id}-title` : undefined}>{title}</h2>
        {actions && <div className="row">{actions}</div>}
      </div>
      {children}
    </section>
  )
}

type FieldProps = {
  id: string
  label: string
  hint?: ReactNode
  error?: string | null
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactNode
}

/** A labelled form control with hint and error wired through aria-describedby. */
export function Field({ id, label, hint, error, children }: FieldProps) {
  const described = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-describedby': described, 'aria-invalid': error ? true : undefined })}
      {hint && (
        <span className="hint" id={`${id}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  )
}

export function parseJsonObject(text: string, label = 'value'): { value?: Record<string, unknown>; error?: string } {
  if (!text.trim()) return { value: {} }
  try {
    const parsed = JSON.parse(text) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return { error: `${label} must be a JSON object` }
    return { value: parsed as Record<string, unknown> }
  } catch (error) {
    return { error: `${label} is not valid JSON: ${(error as Error).message}` }
  }
}

export function parseJsonArray(text: string, label = 'value'): { value?: unknown[]; error?: string } {
  if (!text.trim()) return { value: [] }
  try {
    const parsed = JSON.parse(text) as unknown
    if (!Array.isArray(parsed)) return { error: `${label} must be a JSON array` }
    return { value: parsed }
  } catch (error) {
    return { error: `${label} is not valid JSON: ${(error as Error).message}` }
  }
}
