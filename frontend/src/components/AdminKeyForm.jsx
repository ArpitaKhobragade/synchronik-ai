import { useState } from 'react'
import { api } from '../api/client.js'
import { friendlyError } from '../lib/errors.js'
import Icon from './Icon.jsx'

/** Validates an admin key via POST /api/admin/verify before accepting it. */
export default function AdminKeyForm({ onVerified, compact = false }) {
  const [key, setKey] = useState('')
  const [state, setState] = useState({ busy: false, error: null })

  const submit = async (e) => {
    e.preventDefault()
    const k = key.trim()
    if (!k) return
    setState({ busy: true, error: null })
    try {
      await api.verifyAdmin(k)
      setKey('')
      setState({ busy: false, error: null })
      onVerified(k)
    } catch (err) {
      setState({ busy: false, error: err.code === 'unauthorized' ? 'That admin key is not valid.' : friendlyError(err) })
    }
  }

  return (
    <form className={`admin-form ${compact ? 'compact' : ''}`} onSubmit={submit}>
      <label className="field-label" htmlFor={compact ? 'admin-key-settings' : 'admin-key'}>Admin key</label>
      <div className="admin-form-row">
        <span className="input-icon"><Icon name="key" size={15} /></span>
        <input id={compact ? 'admin-key-settings' : 'admin-key'} className="input" type="password" autoComplete="off" spellCheck={false} autoCapitalize="off"
          placeholder="Enter admin key" value={key} onChange={(e) => setKey(e.target.value)}
          aria-invalid={Boolean(state.error)} aria-describedby={state.error ? 'admin-key-err' : undefined} />
        <button type="submit" className="btn btn-primary" disabled={state.busy || !key.trim()}>{state.busy ? 'Verifying…' : 'Unlock'}</button>
      </div>
      {state.error && <p id="admin-key-err" className="field-error" role="alert">{state.error}</p>}
      <p className="muted small">Stored only for this browser tab (sessionStorage) and sent as the X-Admin-Key header.</p>
    </form>
  )
}
