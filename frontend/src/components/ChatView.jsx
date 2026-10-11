import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat } from '../hooks/useChat.js'
import { useToast } from '../hooks/useToast.js'
import { friendlyError, isRetryable } from '../lib/errors.js'
import { classifyFile, validateFile } from '../lib/files.js'
import { stageLabel } from '../lib/stages.js'
import ChatInput from './ChatInput.jsx'
import Icon from './Icon.jsx'
import MessageList from './MessageList.jsx'
import WelcomeScreen from './WelcomeScreen.jsx'

/** The chat surface: messages, composer, drag-and-drop. Shared by the full app and the widget. */
export default function ChatView({ conversationId, onConversationId, onActivity, onTitle, prefs, compact = false, inputRef, onNewChat }) {
  const chat = useChat({ conversationId, onConversationId, onActivity })
  const [image, setImage] = useState(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const toast = useToast()
  const firstUser = chat.messages.find((m) => m.role === 'user')
  const title = chat.title || (firstUser ? (firstUser.content.length > 60 ? `${firstUser.content.slice(0, 59)}…` : firstUser.content) : null)

  useEffect(() => { if (onTitle) onTitle(title) }, [title, onTitle])

  const clearImage = useCallback(() => {
    setImage((img) => { if (img) URL.revokeObjectURL(img.url); return null })
  }, [])

  const acceptFile = useCallback((file, hint) => {
    const kind = hint || classifyFile(file)
    if (!kind) {
      toast.push({ tone: 'error', message: `“${file.name}” isn’t supported. Use an image (PNG, JPEG, WebP, GIF) or a PDF/DOCX document.` })
      return
    }
    const err = validateFile(file, kind)
    if (err) { toast.push({ tone: 'error', message: err }); return }
    if (kind === 'image') {
      setImage((img) => { if (img) URL.revokeObjectURL(img.url); return { file, url: URL.createObjectURL(file) } })
    } else {
      chat.attachDocument(file)
    }
  }, [toast, chat])

  const send = (text) => {
    if (image) {
      chat.sendImage(image.file, text, image.url)
      setImage(null) // the object URL now belongs to the sent message
    } else {
      chat.send(text, { streaming: prefs.streaming })
    }
  }

  const onRetry = useCallback((key) => chat.retry(key, { streaming: prefs.streaming }), [chat, prefs.streaming])

  const dragProps = {
    onDragEnter: (e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); dragDepth.current += 1; setDragging(true) } },
    onDragOver: (e) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() },
    onDragLeave: () => { dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false) },
    onDrop: (e) => {
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      const file = e.dataTransfer.files && e.dataTransfer.files[0]
      if (file && !chat.busy) acceptFile(file)
    },
  }

  const pending = chat.messages.find((m) => m.status === 'pending' || m.status === 'streaming')
  const live = pending ? (pending.status === 'streaming' ? 'Generating answer…' : stageLabel(pending.stage, pending.stageLabel)) : ''
  const empty = chat.messages.length === 0

  return (
    <div className={`chat-view ${compact ? 'chat-compact' : ''}`} {...dragProps}>
      <div className="sr-only" aria-live="polite" role="status">{live}</div>

      {chat.loading && (
        <div className="center-state" aria-busy="true"><span className="spinner" aria-hidden="true" /> Loading conversation…</div>
      )}

      {!chat.loading && chat.error && (
        <div className="center-state">
          <Icon name="alert" size={22} />
          <p>{chat.error.code === 'not_found' ? 'This conversation no longer exists.' : friendlyError(chat.error)}</p>
          <div className="center-actions">
            {chat.error.code !== 'not_found' && isRetryable(chat.error) && (
              <button type="button" className="btn btn-ghost" onClick={chat.reload}>
                <Icon name="refresh" size={16} /> Retry
              </button>
            )}
            {onNewChat && <button type="button" className="btn btn-primary" onClick={onNewChat}>Start a new chat</button>}
          </div>
        </div>
      )}

      {!chat.loading && !chat.error && (
        empty ? (
          <div className="msg-scroll">
            <div className="msg-column">
              <WelcomeScreen compact={compact} onPick={(t) => chat.send(t, { streaming: prefs.streaming })} disabled={chat.busy} />
            </div>
          </div>
        ) : (
          <MessageList
            messages={chat.messages}
            canRegenerate={Boolean(conversationId) && !chat.busy}
            onRetry={onRetry}
            onRegenerate={chat.regenerate}
            onFeedback={chat.setFeedback}
            onDismiss={chat.dismiss}
          />
        )
      )}

      <div className="composer-wrap">
        <ChatInput
          ref={inputRef}
          compact={compact}
          busy={chat.busy}
          disabled={chat.loading}
          image={image}
          onSend={send}
          onStop={chat.stop}
          onPickFile={acceptFile}
          onClearImage={clearImage}
        />
      </div>

      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <Icon name="upload" size={28} />
          <p>Drop an image to ask about it, or a PDF/DOCX to add it to this conversation</p>
        </div>
      )}
    </div>
  )
}
