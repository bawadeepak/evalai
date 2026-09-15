import { describe, expect, it } from 'vitest'
import { formatInterval, formatMs, formatSigned, formatValue, metricText } from './format'
import { metric } from '../test/fixtures'

describe('formatting', () => {
  it('never renders a missing value as zero', () => {
    expect(formatValue(null, 'fraction')).toBe('Unavailable')
    expect(formatValue(undefined, 'ms')).toBe('Unavailable')
    expect(metricText(metric({ value: null, unavailable_reason: 'no graded repeats' }))).toBe('Unavailable')
  })

  it('formats by unit', () => {
    expect(formatValue(0.9, 'fraction of graded repeats')).toBe('90.0%')
    expect(formatValue(0.81052, 'probability two repeats match')).toBe('81.1%')
    expect(formatValue(0.325, 'nats')).toBe('0.325 nats')
    expect(formatMs(0.05)).toBe('0.05 ms')
    expect(formatMs(1500)).toBe('1.50 s')
  })

  it('shows the documented Wilson interval for 18 of 20', () => {
    const m = metric()
    expect(formatInterval(m.uncertainty, m.unit)).toBe('69.9–97.2%')
  })

  it('signs deltas and treats tiny values as zero', () => {
    expect(formatSigned(-0.1, 'fraction')).toBe('−10.0 pts')
    expect(formatSigned(4.6e-18, 'fraction')).toBe('±0.0 pts')
    expect(formatSigned(null)).toBe('Unavailable')
  })
})
