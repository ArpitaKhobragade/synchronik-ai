import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../hooks/useToast.js'
import { friendlyError } from '../lib/errors.js'
import Icon from './Icon.jsx'

const REASONS = [
  ['incorrect', 'Incorrect answer'],
  ['not_relevant', 'Not relevant'],
  ['missing_info', 'Missing information'],
  ['poor_explanation', 'Poor explanation'],
  ['other', 'Other'],
]

export default function FeedbackButtons({ messageId, value, onChange }) {
  const [popover, setPopover] = useState(false)
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [saving, setSaving] = useState(false)
  const popRef = useRef(null)
  const toast = useToast()

  useEffect(() => {
    if (!popover) return
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setPopover(false) } }
    const onDown = (e) => { if (popRef.current && !popRef.current.contains(e.target)) setPopover(false) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown) }
  }, [popover])

  if (messageId == null) return null

  const submit = async (rating, extra = {}) => {
    setSaving(true)
    try {
      await api.feedback({ message_id: messageId, rating, ...extra })
      onChange(rating)
      setPopover(false)
      toast.push({ tone: 'success', message: rating === 'positive' ? 'Thanks — glad it helped.' : 'Thanks — your feedback helps improve answers.' })
    } catch (e) {
      toast.push({ tone: 'error', message: friendlyError(e) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="feedback" ref={popRef}>
      <button type="button" className={`icon-btn icon-btn-sm ${value === 'positive' ? 'on-pos' : ''}`} aria-pressed={value === 'positive'}
        aria-label="Helpful" title="Helpful" disabled={saving} onClick={() => submit('positive')}>
        <Icon name="thumbUp" size={15} />
      </button>
      <button type="button" className={`icon-btn icon-btn-sm ${value === 'negative' ? 'on-neg' : ''}`} aria-pressed={value === 'negative'}
        aria-label="Not helpful" title="Not helpful" aria-expanded={popover} disabled={saving} onClick={() => setPopover((p) => !p)}>
        <Icon name="thumbDown" size={15} />
      </button>
      {popover && (
        <form className="popover" aria-label="Tell us what went wrong" onSubmit={(e) => { e.preventDefault(); submit('negative', { ...(reason ? { reason } : {}), ...(comment.trim() ? { comment: comment.trim() } : {}) }) }}>
          <p className="popover-title">What went wrong?</p>
          <div className="reason-chips" role="radiogroup" aria-label="Reason">
            {REASONS.map(([k, label]) => (
              <button key={k} type="button" role="radio" aria-checked={reason === k} className={`chip ${reason === k ? 'chip-on' : ''}`} onClick={() => setReason(k)}>
                {label}
              </button>
            ))}
          </div>
          <textarea className="input" rows={2} maxLength={1000} placeholder="Optional comment" aria-label="Optional comment"
            value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="popover-actions">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPopover(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>{saving ? 'Sending…' : 'Send feedback'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
