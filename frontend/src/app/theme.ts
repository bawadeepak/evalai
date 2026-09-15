import { useCallback, useEffect, useState } from 'react'
import { readStorage, STORAGE_KEYS, writeStorage } from './storage'

export type ThemeChoice = 'system' | 'light' | 'dark'

function prefersDark(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
}

export function applyTheme(choice: ThemeChoice): void {
  const dark = choice === 'dark' || (choice === 'system' && prefersDark())
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function initialTheme(): ThemeChoice {
  const stored = readStorage(STORAGE_KEYS.theme)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(initialTheme)
  useEffect(() => {
    applyTheme(choice)
    if (choice !== 'system' || !window.matchMedia) return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = () => applyTheme('system')
    media.addEventListener?.('change', listener)
    return () => media.removeEventListener?.('change', listener)
  }, [choice])
  const update = useCallback((next: ThemeChoice) => {
    writeStorage(STORAGE_KEYS.theme, next === 'system' ? null : next)
    setChoice(next)
  }, [])
  return [choice, update]
}
