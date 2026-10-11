import { useCallback, useSyncExternalStore } from 'react'

// Tiny hash router: #/chat, #/chat/:id, #/knowledge
const subscribe = (cb) => {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}
const getHash = () => window.location.hash

export function parseHash(hash) {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'knowledge') return { page: 'knowledge', id: null }
  if (parts[0] === 'chat' && parts[1]) return { page: 'chat', id: decodeURIComponent(parts[1]) }
  return { page: 'chat', id: null }
}

export function navigate(path, { replace = false } = {}) {
  const hash = '#' + path
  if (window.location.hash === hash) return
  if (replace) {
    window.history.replaceState(null, '', hash)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    window.location.hash = path
  }
}

export function useHashRoute() {
  const hash = useSyncExternalStore(subscribe, getHash, () => '')
  const route = parseHash(hash)
  const go = useCallback((path, opts) => navigate(path, opts), [])
  return [route, go]
}
