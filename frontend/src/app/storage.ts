// Browser-local preferences (reviewer name, theme, selected project, drafts).
// Nothing here is sent to the server except as explicit request fields.

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    /* storage unavailable (private mode): preferences last for this session only */
  }
}

export function readJson<T>(key: string): T | null {
  const text = readStorage(key)
  if (!text) return null
  try {
    return JSON.parse(text) as T
  } catch {
    return null
  }
}

export function writeJson(key: string, value: unknown): void {
  writeStorage(key, value === null || value === undefined ? null : JSON.stringify(value))
}

export const STORAGE_KEYS = {
  project: 'evalai.projectId',
  reviewer: 'evalai.reviewer',
  theme: 'evalai.theme',
  wizardDraft: 'evalai.wizardDraft',
  markdown: 'evalai.renderMarkdown',
}

export function getReviewer(): string {
  return readStorage(STORAGE_KEYS.reviewer) ?? ''
}

export function setReviewer(name: string): void {
  writeStorage(STORAGE_KEYS.reviewer, name.trim() || null)
}
