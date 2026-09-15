// J/K queue navigation, Enter to open, Escape to close — only when the user is
// not typing. No single key triggers a destructive or irreversible action.

import { useEffect, useRef } from 'react'

export type KeyboardHandlers = {
  next?: () => void
  prev?: () => void
  open?: () => void
  close?: () => void
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type
    return !['checkbox', 'radio', 'button', 'submit', 'range'].includes(type)
  }
  return false
}

function isInteractive(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && !!target.closest('button, a, [role="button"], [role="tab"], input, select, textarea')
}

export function handleKey(event: KeyboardEvent, handlers: KeyboardHandlers): boolean {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return false
  if (isTypingTarget(event.target)) return false
  switch (event.key) {
    case 'j':
    case 'J':
      if (!handlers.next) return false
      handlers.next()
      return true
    case 'k':
    case 'K':
      if (!handlers.prev) return false
      handlers.prev()
      return true
    case 'Enter':
      // Enter on a focused control keeps its native meaning.
      if (!handlers.open || isInteractive(event.target)) return false
      handlers.open()
      return true
    case 'Escape':
      if (!handlers.close) return false
      handlers.close()
      return true
    default:
      return false
  }
}

export function useKeyboardNav(handlers: KeyboardHandlers, enabled = true): void {
  const ref = useRef(handlers)
  ref.current = handlers
  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (handleKey(event, ref.current)) event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}
