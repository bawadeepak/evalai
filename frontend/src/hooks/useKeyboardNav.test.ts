import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { handleKey, isTypingTarget, useKeyboardNav } from './useKeyboardNav'

function press(key: string, target: EventTarget = document.body, init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

describe('keyboard navigation', () => {
  it('maps J/K/Enter/Escape to queue actions', () => {
    const handlers = { next: vi.fn(), prev: vi.fn(), open: vi.fn(), close: vi.fn() }
    renderHook(() => useKeyboardNav(handlers))
    press('j')
    press('K')
    press('Enter')
    press('Escape')
    expect(handlers.next).toHaveBeenCalledTimes(1)
    expect(handlers.prev).toHaveBeenCalledTimes(1)
    expect(handlers.open).toHaveBeenCalledTimes(1)
    expect(handlers.close).toHaveBeenCalledTimes(1)
  })

  it('ignores keys while typing and with modifiers', () => {
    const handlers = { next: vi.fn(), prev: vi.fn() }
    renderHook(() => useKeyboardNav(handlers))
    const input = document.createElement('input')
    const textarea = document.createElement('textarea')
    document.body.append(input, textarea)
    press('j', input)
    press('k', textarea)
    press('j', document.body, { ctrlKey: true })
    press('j', document.body, { metaKey: true })
    expect(handlers.next).not.toHaveBeenCalled()
    expect(handlers.prev).not.toHaveBeenCalled()
    expect(isTypingTarget(input)).toBe(true)
    input.remove()
    textarea.remove()
  })

  it('keeps the native meaning of Enter on buttons and binds nothing destructive', () => {
    const open = vi.fn()
    const button = document.createElement('button')
    document.body.append(button)
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
    Object.defineProperty(event, 'target', { value: button })
    expect(handleKey(event, { open })).toBe(false)
    expect(open).not.toHaveBeenCalled()
    for (const key of ['d', 'Delete', 'Backspace', 'c', 'p']) {
      const e = new KeyboardEvent('keydown', { key })
      expect(handleKey(e, { next: vi.fn(), prev: vi.fn(), open: vi.fn(), close: vi.fn() })).toBe(false)
    }
    button.remove()
  })
})
