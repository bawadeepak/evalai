// Minimal fetch wrapper for the {data, meta} / {error} envelopes.

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  requestId: string | null

  constructor(status: number, code: string, message: string, details: unknown = null, requestId: string | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }

  /** The server could not be reached at all (as opposed to answering with an error). */
  get disconnected(): boolean {
    return this.status === 0
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>

export function buildUrl(path: string, params?: Params): string {
  const url = `/api/v1${path}`
  if (!params) return url
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `${url}?${text}` : url
}

async function parse<T>(response: Response): Promise<{ data: T; meta: Record<string, unknown> }> {
  const type = response.headers.get('content-type') ?? ''
  const body = type.includes('application/json') ? await response.json().catch(() => null) : null
  if (!response.ok) {
    const error = body?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'http_error',
      error?.message ?? `The server answered ${response.status}`,
      error?.details ?? null,
      error?.request_id ?? null,
    )
  }
  if (body === null) throw new ApiError(response.status, 'bad_response', 'The server returned a non-JSON response')
  return { data: body.data as T, meta: (body.meta ?? {}) as Record<string, unknown> }
}

async function send<T>(method: string, path: string, options: { params?: Params; body?: unknown; headers?: Record<string, string>; raw?: BodyInit } = {}) {
  let response: Response
  try {
    response = await fetch(buildUrl(path, options.params), {
      method,
      headers: {
        Accept: 'application/json',
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      body: options.raw ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    })
  } catch (cause) {
    throw new ApiError(0, 'disconnected', 'Cannot reach the Eval Triage service. Is `make start` running?', { cause: String(cause) })
  }
  return parse<T>(response)
}

export const api = {
  get: <T>(path: string, params?: Params) => send<T>('GET', path, { params }),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>, params?: Params) =>
    send<T>('POST', path, { body: body ?? {}, headers, params }),
  put: <T>(path: string, body: unknown) => send<T>('PUT', path, { body }),
  upload: <T>(path: string, data: Blob, params?: Params) =>
    send<T>('POST', path, { raw: data, params, headers: { 'Content-Type': 'application/zip' } }),
}

/** Download a response body as a file via a temporary object URL (same-origin only). */
export async function downloadFile(path: string, filename: string, params?: Params): Promise<void> {
  const response = await fetch(buildUrl(path, params))
  if (!response.ok) {
    await parse(response)
  }
  const blob = await response.blob()
  saveBlob(blob, filename)
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** Field-level errors from a 422 response, keyed by dotted path. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  const out: Record<string, string> = {}
  const details = error.details as unknown
  const list = Array.isArray(details)
    ? details
    : details && typeof details === 'object' && Array.isArray((details as { errors?: unknown[] }).errors)
      ? (details as { errors: unknown[] }).errors
      : []
  for (const item of list as Record<string, unknown>[]) {
    if (!item || typeof item !== 'object') continue
    if (typeof item.field === 'string') out[item.field] = String(item.message ?? '')
    else if (Array.isArray(item.loc)) out[(item.loc as unknown[]).filter((p) => p !== 'body').join('.')] = String(item.msg ?? '')
    else if (typeof item.path === 'string') out[item.path] = String(item.message ?? '')
  }
  return out
}
