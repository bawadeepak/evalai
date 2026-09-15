// Live run progress over SSE (/runs/:id/events). The browser's EventSource
// reconnects with Last-Event-ID; while it is reconnecting the page shows a
// disconnected notice and keeps the last snapshot. Queries refetch on events.

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { RunEvent } from '../api/types'

/** Mirrors backend/eval_triage/execution/events.py EVENT_TYPES (EventSource needs named listeners). */
export const RUN_EVENT_TYPES = [
  'run.queued',
  'run.started',
  'trial.started',
  'attempt.finished',
  'artifact.created',
  'grade.created',
  'run.progress',
  'run.finished',
  'run.cancelled',
  'run.error',
  'grading.started',
  'grading.finished',
]

export type StreamState = 'idle' | 'open' | 'reconnecting' | 'ended'

export function useRunEvents(runId: string | undefined, active: boolean) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<StreamState>('idle')
  const [lastEvent, setLastEvent] = useState<RunEvent | null>(null)

  useEffect(() => {
    if (!runId || !active || typeof EventSource === 'undefined') return
    const source = new EventSource(`/api/v1/runs/${runId}/events`)
    let timer: ReturnType<typeof setTimeout> | null = null
    const refresh = () => {
      if (timer) return
      timer = setTimeout(() => {
        timer = null
        void queryClient.invalidateQueries({ queryKey: ['run', runId] })
        void queryClient.invalidateQueries({ queryKey: ['summary', runId] })
        void queryClient.invalidateQueries({ queryKey: ['triage', runId] })
      }, 600)
    }
    const onEvent = (event: MessageEvent<string>) => {
      setState('open')
      try {
        setLastEvent(JSON.parse(event.data) as RunEvent)
      } catch {
        /* keep the previous event */
      }
      refresh()
    }
    source.onopen = () => setState('open')
    source.onerror = () => setState(source.readyState === EventSource.CLOSED ? 'ended' : 'reconnecting')
    for (const type of RUN_EVENT_TYPES) source.addEventListener(type, onEvent as EventListener)
    source.addEventListener('stream.end', () => {
      setState('ended')
      source.close()
      refresh()
    })
    return () => {
      source.close()
      if (timer) clearTimeout(timer)
    }
  }, [runId, active, queryClient])

  return { state, lastEvent }
}
