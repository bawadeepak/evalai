// Number formatting by unit. Unknown or missing values are words, never 0.

import type { MetricValue, Uncertainty } from './types'

const PERCENT_UNITS = ['fraction', 'probability', 'rate']

export function isPercentUnit(unit: string | undefined | null): boolean {
  if (!unit) return false
  const lower = unit.toLowerCase()
  return PERCENT_UNITS.some((u) => lower.includes(u))
}

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'Unavailable'
  if (Object.is(value, -0)) value = 0
  if (Number.isInteger(value)) return value.toLocaleString('en')
  return Number(value.toFixed(digits)).toLocaleString('en', { maximumFractionDigits: digits })
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'Unavailable'
  const pct = value * 100
  return `${(Object.is(pct, -0) ? 0 : pct).toFixed(digits)}%`
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Unavailable'
  if (value < 1) return `${value.toFixed(2)} ms`
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

export function formatValue(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined) return 'Unavailable'
  if (unit === 'ms') return formatMs(value)
  if (unit === 'nats') return `${formatNumber(value, 3)} nats`
  if (isPercentUnit(unit)) return formatPercent(value)
  return formatNumber(value)
}

export function formatSigned(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined) return 'Unavailable'
  const clean = Math.abs(value) < 1e-12 ? 0 : value
  const sign = clean > 0 ? '+' : clean < 0 ? '−' : '±'
  const magnitude = Math.abs(clean)
  if (isPercentUnit(unit) || unit === 'fraction') return `${sign}${(magnitude * 100).toFixed(1)} pts`
  return `${sign}${formatNumber(magnitude)}`
}

export function formatInterval(u: Uncertainty | null | undefined, unit?: string | null): string | null {
  if (!u || u.lower === null || u.upper === null) return null
  if (isPercentUnit(unit)) return `${(u.lower * 100).toFixed(1)}–${(u.upper * 100).toFixed(1)}%`
  return `${formatNumber(u.lower)}–${formatNumber(u.upper)}`
}

export function metricText(metric: MetricValue | null | undefined): string {
  if (!metric) return 'Unavailable'
  if (metric.value === null) return 'Unavailable'
  return formatValue(metric.value, metric.unit)
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('en-AU', { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—'
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()
  if (ms < 0 || Number.isNaN(ms)) return '—'
  if (ms < 1000) return `${ms} ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  return `${m} min ${s % 60} s`
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return 'Unknown'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export function shortHash(hash: string | null | undefined, length = 10): string {
  return hash ? hash.slice(0, length) : '—'
}

export function humanize(text: string | null | undefined): string {
  if (!text) return ''
  return text.replace(/_/g, ' ')
}
