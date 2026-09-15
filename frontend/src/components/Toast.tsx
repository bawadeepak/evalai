// Toasts summarise completed actions. Important errors stay inline on the page.

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

type Toast = { id: number; message: string }
const ToastContext = createContext<(message: string) => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const push = useCallback(
    (message: string) => {
      const id = next.current++
      setToasts((all) => [...all.slice(-3), { id, message }])
      setTimeout(() => dismiss(id), 5000)
    },
    [dismiss],
  )
  const value = useMemo(() => push, [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span>{t.message}</span>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
