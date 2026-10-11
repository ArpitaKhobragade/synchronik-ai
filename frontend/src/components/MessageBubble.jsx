import { memo, useState } from 'react'
import { friendlyError, isRetryable } from '../lib/errors.js'
import { formatTime } from '../lib/format.js'
import FeedbackButtons from './FeedbackButtons.jsx'
import Icon from './Icon.jsx'
import { LogoMark } from './Logo.jsx'
import { stripCitations } from '../lib/citations.js'
import Markdown from './Markdown.jsx'
import SourceCards from './SourceCards.jsx'
import ThinkingIndicator from './ThinkingIndicator.jsx'

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard unavailable */ }
  }
  return (
    <button type="button" className="icon-btn icon-btn-sm" aria-label={copied ? 'Copied' : 'Copy answer'} title={copied ? 'Copied' : 'Copy'} onClick={copy}>
      <span key={copied ? 'done' : 'idle'} className={copied ? 'icon-pop copied' : ''}><Icon name={copied ? 'check' : 'copy'} size={15} /></span>
    </button>
  )
}

function AttachmentEvent({ msg, onDismiss }) {
  const pctText = typeof msg.progress === 'number' ? `${Math.round(msg.progress * 100)}%` : ''
  return (
    <div className={`event-row event-${msg.status}`} role="status">
      <Icon name={msg.status === 'error' ? 'alert' : msg.status === 'done' ? 'check' : 'file'} size={16} />
      <div className="event-text">
        <strong>{msg.name}</strong>
        {msg.status === 'uploading' && (
          <>
            <span> — uploading {pctText}</span>
            <span className="progress" aria-hidden="true"><span style={{ width: pctText || '0%' }} /></span>
          </>
        )}
        {msg.status === 'processing' && <span> — processing document…</span>}
        {msg.status === 'done' && (
          <span> — Document processed successfully and added to this conversation{msg.chunks ? ` (${msg.chunks} ${msg.chunks === 1 ? 'section' : 'sections'} indexed)` : ''}.</span>
        )}
        {msg.status === 'error' && <span> — {friendlyError(msg.error)}</span>}
      </div>
      {msg.status === 'error' && (
        <button type="button" className="icon-btn icon-btn-sm" aria-label="Dismiss" onClick={() => onDismiss(msg.key)}><Icon name="close" size={14} /></button>
      )}
    </div>
  )
}

function MessageBubble({ msg, isLastAssistant, canRegenerate, onRetry, onRegenerate, onFeedback, onDismiss }) {

  if (msg.role === 'event') return <AttachmentEvent msg={msg} onDismiss={onDismiss} />

  if (msg.role === 'user') {
    const att = msg.attachment
    return (
      <div className="msg msg-user">
        <div className="bubble-user">
          {att && att.kind === 'image' && att.previewUrl && <img className="msg-image" src={att.previewUrl} alt={`Attached image ${att.name}`} />}
          {att && !(att.kind === 'image' && att.previewUrl) && (
            <span className="msg-attach"><Icon name={att.kind === 'image' ? 'image' : 'file'} size={14} /> {att.name}</span>
          )}
          <p className="user-text">{msg.content}</p>
        </div>
        <time className="msg-time" dateTime={msg.created_at}>{formatTime(msg.created_at)}</time>
      </div>
    )
  }

  const pending = msg.status === 'pending'
  const streaming = msg.status === 'streaming'
  const done = msg.status === 'done'

  return (
    <article className="msg msg-assistant" aria-label="Assistant answer">
      <div className="msg-avatar" aria-hidden="true"><LogoMark size={28} /></div>
      <div className="msg-body">
        {pending && <ThinkingIndicator stage={msg.stage} label={msg.stageLabel} progress={msg.progress} />}

        {msg.content && (
          <div className={streaming ? 'streaming' : ''}>
            <Markdown text={msg.content} />
          </div>
        )}

        {msg.status === 'stopped' && (
          <div className="inline-note">
            <Icon name="stop" size={14} /> Generation stopped.
            {msg.request && <button type="button" className="btn-link" onClick={() => onRetry(msg.key)}>Retry</button>}
          </div>
        )}

        {msg.status === 'error' && (
          <div className="inline-error" role="alert">
            <Icon name="alert" size={16} />
            <span>{friendlyError(msg.error)}</span>
            {isRetryable(msg.error) && msg.request && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => onRetry(msg.key)}>
                <Icon name="refresh" size={14} /> Retry
              </button>
            )}
          </div>
        )}

        {(done || streaming) && <SourceCards sources={msg.sources} msgKey={msg.key} />}

        {done && (
          <div className="msg-actions">
            <CopyButton text={stripCitations(msg.content)} />
            {isLastAssistant && canRegenerate && (
              <button type="button" className="icon-btn icon-btn-sm" aria-label="Regenerate answer" title="Regenerate" onClick={() => onRegenerate(msg.key)}>
                <Icon name="refresh" size={15} />
              </button>
            )}
            <FeedbackButtons messageId={msg.id} value={msg.feedback} onChange={(v) => onFeedback(msg.key, v)} />
            <time className="msg-time" dateTime={msg.created_at}>{formatTime(msg.created_at)}</time>
          </div>
        )}
      </div>
    </article>
  )
}

export default memo(MessageBubble)
