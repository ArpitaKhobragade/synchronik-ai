import { useCallback, useEffect, useState } from 'react'

const KEY = 'snk.prefs.v1'
export const DEFAULT_PREFS = { theme: 'system', streaming: true }

function load() {
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS
  } catch {
    return DEFAULT_PREFS
  }
}

/** Non-secret UI preferences, persisted in localStorage (best effort). */
export function usePrefs() {
  const [prefs, setPrefs] = useState(load)

  useEffect(() => {
    try { window.localStorage.setItem(KEY, JSON.stringify(prefs)) } catch { /* storage unavailable */ }
  }, [prefs])

  useEffect(() => {
    document.documentElement.dataset.theme = prefs.theme
  }, [prefs.theme])

  const update = useCallback((patch) => setPrefs((p) => ({ ...p, ...patch })), [])
  return [prefs, update]
}

const ADMIN_KEY = 'snk.adminKey'
export function readAdminKey() {
  try { return window.sessionStorage.getItem(ADMIN_KEY) || '' } catch { return '' }
}
export function writeAdminKey(value) {
  try {
    if (value) window.sessionStorage.setItem(ADMIN_KEY, value)
    else window.sessionStorage.removeItem(ADMIN_KEY)
  } catch { /* storage unavailable */ }
}

const LAST_ID = 'snk.lastConversation'
export function readLastConversation() {
  try { return window.localStorage.getItem(LAST_ID) } catch { return null }
}
export function writeLastConversation(id) {
  try {
    if (id) window.localStorage.setItem(LAST_ID, id)
    else window.localStorage.removeItem(LAST_ID)
  } catch { /* storage unavailable */ }
}
