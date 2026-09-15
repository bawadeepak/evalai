// WCAG AA: every text/background token pair used by the UI reaches 4.5:1 in
// both themes. Values are read from tokens.css so the test cannot drift.

import { describe, expect, it } from 'vitest'
import css from './tokens.css?raw'

function block(selector: RegExp): Record<string, string> {
  const match = selector.exec(css)
  if (!match) throw new Error(`no block for ${selector}`)
  const body = css.slice(match.index + match[0].length, css.indexOf('}', match.index))
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]!] = m[2]!
  return out
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi! + 0.05) / (lo! + 0.05)
}

const PAIRS: [string, string][] = [
  ['ink', 'bg'],
  ['ink', 'surface'],
  ['ink', 'surface-2'],
  ['muted', 'bg'],
  ['muted', 'surface'],
  ['muted', 'surface-2'],
  ['accent', 'surface'],
  ['accent', 'selected'],
  ['accent-ink', 'accent'],
  ['surface', 'ink'],
  ['warning', 'warning-bg'],
  ['danger', 'danger-bg'],
  ['info', 'info-bg'],
  ['unavailable', 'unavailable-bg'],
  ['ink', 'selected'],
]

describe('WCAG AA contrast', () => {
  const light = block(/:root\s*\{/)
  const dark = { ...light, ...block(/:root\[data-theme='dark'\]\s*\{/) }
  for (const [theme, palette] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    for (const [fg, bg] of PAIRS) {
      it(`${theme}: --${fg} on --${bg} ≥ 4.5:1`, () => {
        expect(palette[fg], `missing --${fg}`).toBeDefined()
        expect(palette[bg], `missing --${bg}`).toBeDefined()
        expect(contrast(palette[fg]!, palette[bg]!)).toBeGreaterThanOrEqual(4.5)
      })
    }
  }
})
