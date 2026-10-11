import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import MessageBubble from './MessageBubble.jsx'

const THRESHOLD = 120

export default function MessageList({ messages, canRegenerate, onRetry, onRegenerate, onFeedback, onDismiss, children }) {
  const scrollRef = useRef(null)
  const nearBottomRef = useRef(true)
  const [showJump, setShowJump] = useState(false)

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < THRESHOLD
    nearBottomRef.current = near
    setShowJump(!near)
  }

  // Auto-scroll only while the reader is already near the bottom.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && nearBottomRef.current) el.scrollTop = el.scrollHeight
  }, [messages])

  // A freshly sent user message always brings the view to the bottom.
  const lastUser = [...messages].reverse().find((m) => m.role === 'user')
  const lastUserKey = lastUser && lastUser.key
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !lastUserKey) return
    nearBottomRef.current = true
    el.scrollTop = el.scrollHeight
  }, [lastUserKey])

  const jump = () => {
    const el = scrollRef.current
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
    nearBottomRef.current = true
  }

  let lastAssistantKey = null
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant') { lastAssistantKey = messages[i].key; break }
  }

  return (
    <div className="msg-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="msg-column" role="log" aria-label="Conversation" aria-live="off">
        {children}
        {messages.map((m) => (
          <MessageBubble
            key={m.key}
            msg={m}
            isLastAssistant={m.key === lastAssistantKey}
            canRegenerate={canRegenerate}
            onRetry={onRetry}
            onRegenerate={onRegenerate}
            onFeedback={onFeedback}
            onDismiss={onDismiss}
          />
        ))}
      </div>
      {showJump && (
        <button type="button" className="jump-latest" onClick={jump}>
          <Icon name="arrowDown" size={15} /> Jump to latest
        </button>
      )}
    </div>
  )
}
