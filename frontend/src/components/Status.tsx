// Status is shown with words and a symbol as well as colour. Red means a
// confirmed failure, amber a warning or inconclusive result, grey unavailable;
// green never implies statistical certainty.

type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'na'

const RUN: Record<string, [Tone, string, string]> = {
  queued: ['info', '○', 'Queued'],
  running: ['info', '●', 'Running'],
  cancelling: ['warn', '◌', 'Cancelling'],
  completed: ['ok', '✓', 'Completed'],
  completed_with_errors: ['warn', '!', 'Completed with errors'],
  cancelled: ['na', '–', 'Cancelled'],
  failed: ['bad', '×', 'Failed'],
}

const OUTCOME: Record<string, [Tone, string, string]> = {
  pass: ['ok', '✓', 'Pass'],
  fail: ['bad', '×', 'Fail'],
  unresolved: ['warn', '?', 'Unresolved'],
  error: ['warn', '!', 'Grading error'],
  abstain: ['na', '–', 'Abstained'],
  unavailable: ['na', '–', 'Unavailable'],
  not_a_binary_verdict: ['na', '#', 'Numeric only'],
}

const GATE: Record<string, [Tone, string, string]> = {
  ready: ['ok', '✓', 'Ready'],
  blocked: ['bad', '×', 'Blocked'],
  inconclusive: ['warn', '?', 'Inconclusive'],
  descriptive: ['na', '·', 'Descriptive only'],
  pass: ['ok', '✓', 'Within margin'],
  fail: ['bad', '×', 'Outside margin'],
}

const CAPABILITY: Record<string, [Tone, string, string]> = {
  supported: ['ok', '✓', 'Supported'],
  unsupported: ['bad', '×', 'Unsupported'],
  unknown: ['warn', '?', 'Unknown'],
}

const CREDENTIAL: Record<string, [Tone, string, string]> = {
  set: ['ok', '✓', 'Set in environment'],
  missing: ['bad', '×', 'Missing from environment'],
  not_required: ['na', '–', 'Not required'],
}

const TRIAL: Record<string, [Tone, string, string]> = {
  pending: ['na', '○', 'Pending'],
  running: ['info', '●', 'Running'],
  success: ['ok', '✓', 'Success'],
  provider_error: ['warn', '!', 'Provider error'],
  timeout: ['warn', '⧗', 'Timeout'],
  cancelled: ['na', '–', 'Cancelled'],
  invalid_output: ['bad', '×', 'Invalid output'],
  unsupported: ['na', '–', 'Unsupported'],
  skipped: ['na', '–', 'Skipped'],
  interrupted: ['warn', '!', 'Interrupted'],
  indeterminate: ['warn', '?', 'Indeterminate'],
}

const TABLES = { run: RUN, outcome: OUTCOME, gate: GATE, capability: CAPABILITY, credential: CREDENTIAL, trial: TRIAL }

export type StatusKind = keyof typeof TABLES

export function Badge({ tone = 'na', children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {children}
    </span>
  )
}

export function StatusBadge({ kind, value, title }: { kind: StatusKind; value: string | null | undefined; title?: string }) {
  const entry = value ? TABLES[kind][value] : undefined
  const [tone, symbol, label] = entry ?? ['na', '·', value ? value.replace(/_/g, ' ') : 'Unknown']
  return (
    <span className={`badge ${tone}`} title={title} data-status={value ?? 'unknown'}>
      <span aria-hidden="true">{symbol}</span>
      {label}
    </span>
  )
}

export function toneFor(kind: StatusKind, value: string | null | undefined): Tone {
  return (value && TABLES[kind][value]?.[0]) || 'na'
}

export const SEVERITY_TONE: Record<string, Tone> = { critical: 'bad', high: 'warn', medium: 'info', low: 'na' }

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity] ?? 'na'}>{severity}</Badge>
}
