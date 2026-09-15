// Shared UI states: loading, empty, partial, error (with retry), disconnected
// and unavailable. Every page composes these instead of ad-hoc messages.

import type { ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { ApiError } from '../api/client'

export function Loading({ lines = 3, label = 'Loading' }: { lines?: number; label?: string }) {
  return (
    <div className="stack" role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state" data-state="empty">
      <h3>{title}</h3>
      {children && <div className="muted">{children}</div>}
      {action}
    </div>
  )
}

export function Partial({ children }: { children: ReactNode }) {
  return (
    <div className="notice warn" role="status" data-state="partial">
      <span aria-hidden="true">◐</span>
      <div>{children}</div>
    </div>
  )
}

export function Unavailable({ title = 'Unavailable', reason, children }: { title?: string; reason: string; children?: ReactNode }) {
  return (
    <div className="state state-unavailable" data-state="unavailable">
      <h3>{title}</h3>
      <p className="muted">{reason}</p>
      {children}
    </div>
  )
}

export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const apiError = error instanceof ApiError ? error : null
  const disconnected = apiError?.disconnected
  return (
    <div className="state state-error" role="alert" data-state={disconnected ? 'disconnected' : 'error'}>
      <h3>{title ?? (disconnected ? 'Service unreachable' : 'Something went wrong')}</h3>
      <p>{error instanceof Error ? error.message : String(error)}</p>
      {apiError?.requestId && <p className="tiny muted">Request ID {apiError.requestId}</p>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function Disconnected({ children }: { children?: ReactNode }) {
  return (
    <div className="notice warn" role="status" data-state="disconnected">
      <span aria-hidden="true">⚠</span>
      <div>{children ?? 'Live updates disconnected. Reconnecting…'}</div>
    </div>
  )
}

/** Render loading / error states for a query, then the children with its data. */
export function QueryState<T>({
  query,
  children,
  loading,
}: {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
  loading?: ReactNode
}) {
  if (query.isPending) return <>{loading ?? <Loading />}</>
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  return <>{children(query.data as T)}</>
}

export function FieldError({ id, message }: { id: string; message?: string | null }) {
  if (!message) return null
  return (
    <span className="error" id={id} role="alert">
      {message}
    </span>
  )
}
