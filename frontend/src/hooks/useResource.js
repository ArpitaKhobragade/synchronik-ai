import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Fetch data with abort + reload. `loader(signal)` returns a promise; `key` changes trigger a refetch
 * (pass null to skip). Returns { data, error, loading, reload }.
 */
export function useResource(loader, key) {
  const [nonce, setNonce] = useState(0)
  const [result, setResult] = useState({ token: null, data: null, error: null })
  const loaderRef = useRef(loader)
  useEffect(() => { loaderRef.current = loader }, [loader])
  const token = key == null ? null : `${key}#${nonce}`

  useEffect(() => {
    if (token == null) return
    const ctrl = new AbortController()
    loaderRef.current(ctrl.signal)
      .then((data) => setResult({ token, data, error: null }))
      .catch((error) => { if (error.name !== 'AbortError') setResult({ token, data: null, error }) })
    return () => ctrl.abort()
  }, [token])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const fresh = result.token === token
  const keyMatches = result.token != null && token != null && result.token.split('#')[0] === token.split('#')[0]
  return {
    // keep showing the previous data for the same key while reloading
    data: keyMatches ? result.data : null,
    error: fresh ? result.error : null,
    loading: token != null && !fresh,
    reload,
  }
}
