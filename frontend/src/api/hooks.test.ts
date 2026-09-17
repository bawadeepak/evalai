/* eslint-disable react-hooks/rules-of-hooks -- each hook below is a thin wrapper over a mocked useQuery, not a render */
import { describe, expect, it, vi } from 'vitest'
import { useConnectionTest, useExports, useHealth, useJob, useRun, useRuns } from './hooks'

const { captured } = vi.hoisted(() => ({ captured: [] as Record<string, unknown>[] }))

vi.mock('@tanstack/react-query', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-query')>()),
  useQuery: (options: Record<string, unknown>) => {
    captured.push(options)
    return { data: undefined }
  },
}))

function optionsOf(call: () => unknown): Record<string, unknown> {
  captured.length = 0
  call()
  const options = captured[0]
  if (!options) throw new Error('the hook did not call useQuery')
  return options
}

describe('background polling', () => {
  it('keeps polling a job that is waited on while the document is hidden', () => {
    // The calibration fit, connection test and export panels wait for a terminal status. If the poll
    // pauses while the tab is hidden, the job finishes but its result never reaches the screen.
    expect(optionsOf(() => useJob('job-1')).refetchIntervalInBackground).toBe(true)
    expect(optionsOf(() => useConnectionTest('test-1')).refetchIntervalInBackground).toBe(true)
    expect(optionsOf(() => useExports('project-1')).refetchIntervalInBackground).toBe(true)
  })

  it('lets progress polls pause while the document is hidden', () => {
    // These only track progress and refetch when the page is shown again; polling a hidden tab
    // for ever would be a needless stream of requests.
    expect(optionsOf(() => useHealth()).refetchIntervalInBackground).toBeUndefined()
    expect(optionsOf(() => useRuns('project-1')).refetchIntervalInBackground).toBeUndefined()
    expect(optionsOf(() => useRun('run-1')).refetchIntervalInBackground).toBeUndefined()
  })
})
