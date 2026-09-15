import { QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { Providers } from '../app/App'

export function renderWithProviders(ui: ReactElement, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Providers client={client}>{ui}</Providers>
    </MemoryRouter>,
  )
}

type Handler = (url: URL, init?: RequestInit) => unknown

/** Stub fetch with JSON envelopes; records every call. */
export function stubApi(routes: Record<string, Handler>) {
  const calls: { method: string; url: string; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = init?.method ?? 'GET'
    calls.push({ method, url: url.pathname + url.search, body: init?.body ? JSON.parse(String(init.body)) : null })
    const key = `${method} ${url.pathname}`
    const handler = routes[key]
    const data = handler ? handler(url, init) : []
    return new Response(JSON.stringify({ data, meta: {} }), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}
