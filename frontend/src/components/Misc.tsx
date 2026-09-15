import type { ReactNode } from 'react'
import { ApiError, fieldErrors } from '../api/client'

export function Progress({ value, max, label }: { value: number; max: number; label?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="row" style={{ flexWrap: 'nowrap' }}>
      <div
        className="progress grow"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-label={label ?? 'Progress'}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
      <span className="tiny muted num nowrap">
        {value} / {max}
      </span>
    </div>
  )
}

/** Inline, persistent error for a failed action, including field-level details. */
export function ActionError({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null
  const fields = fieldErrors(error)
  const entries = Object.entries(fields)
  const apiError = error instanceof ApiError ? error : null
  return (
    <div className="notice bad" role="alert" data-testid="action-error">
      <span aria-hidden="true">×</span>
      <div className="stack" style={{ gap: 4 }}>
        <strong>{title ?? (error instanceof Error ? error.message : String(error))}</strong>
        {title && error instanceof Error && <span>{error.message}</span>}
        {entries.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {entries.map(([field, message]) => (
              <li key={field}>
                <code>{field || 'request'}</code>: {message}
              </li>
            ))}
          </ul>
        )}
        {apiError?.requestId && <span className="tiny">Request ID {apiError.requestId}</span>}
      </div>
    </div>
  )
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv" style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, auto) 1fr', gap: '4px 14px', margin: 0 }}>
      {items.map(([key, value]) => (
        <div key={key} style={{ display: 'contents' }}>
          <dt className="muted small">{key}</dt>
          <dd style={{ margin: 0, minWidth: 0 }} className="wrap-anywhere">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function Hash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>
  return (
    <code title={value} className="tiny">
      {value.slice(0, 10)}
    </code>
  )
}

export async function readFileText(file: File, maxBytes = 10 * 1024 * 1024): Promise<string> {
  if (file.size > maxBytes) throw new Error(`File is larger than ${Math.round(maxBytes / 1024 / 1024)} MB`)
  return file.text()
}
