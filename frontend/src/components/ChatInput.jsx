import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { DOC_ACCEPT, IMAGE_ACCEPT } from '../lib/files.js'
import Icon from './Icon.jsx'

const MAX_LEN = 4000

const ChatInput = forwardRef(function ChatInput({ busy, disabled, image, onSend, onStop, onPickFile, onClearImage, compact = false }, ref) {
  const [value, setValue] = useState('')
  const [menu, setMenu] = useState(false)
  const taRef = useRef(null)
  const imgInput = useRef(null)
  const docInput = useRef(null)
  const menuRef = useRef(null)

  useImperativeHandle(ref, () => ({ focus: () => taRef.current && taRef.current.focus() }), [])

  // Auto-grow the textarea up to a max height.
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    if (!value) return // single row; avoids measuring before layout settles
    ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`
  }, [value])

  useEffect(() => {
    if (!menu) return
    const onDown = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenu(false) }
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setMenu(false) } }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [menu])

  const text = value.trim()
  const canSend = !busy && !disabled && text.length > 0 && text.length <= MAX_LEN

  const submit = () => {
    if (!canSend) return
    onSend(text)
    setValue('')
  }

  const pick = (kind) => {
    setMenu(false)
    const input = kind === 'image' ? imgInput.current : docInput.current
    if (input) input.click()
  }

  const onFile = (kind) => (e) => {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''
    if (file) onPickFile(file, kind)
  }

  return (
    <div className={`composer ${compact ? 'composer-compact' : ''}`}>
      {image && (
        <div className="composer-preview">
          <img src={image.url} alt={`Selected image ${image.file.name}`} />
          <div className="composer-preview-meta">
            <span className="file-name">{image.file.name}</span>
            <span className="muted small">Ask a question about this image</span>
          </div>
          <button type="button" className="icon-btn icon-btn-sm" aria-label="Remove image" onClick={onClearImage}>
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
      <div className="composer-row">
        <div className="menu-wrap" ref={menuRef}>
          <button type="button" className="icon-btn" aria-label="Add attachment" aria-haspopup="menu" aria-expanded={menu}
            disabled={busy || disabled} onClick={() => setMenu((m) => !m)}>
            <Icon name="paperclip" />
          </button>
          {menu && (
            <div className="menu menu-up" role="menu">
              <button type="button" role="menuitem" className="menu-item" onClick={() => pick('image')}>
                <Icon name="image" size={15} />
                <span><strong>Image</strong><small>Ask about a screenshot · PNG, JPEG, WebP, GIF ≤ 8 MB</small></span>
              </button>
              <button type="button" role="menuitem" className="menu-item" onClick={() => pick('document')}>
                <Icon name="file" size={15} />
                <span><strong>Document</strong><small>Add to this conversation · PDF, DOCX ≤ 20 MB</small></span>
              </button>
            </div>
          )}
        </div>
        <input ref={imgInput} type="file" accept={IMAGE_ACCEPT} hidden onChange={onFile('image')} />
        <input ref={docInput} type="file" accept={DOC_ACCEPT} hidden onChange={onFile('document')} />

        <label className="sr-only" htmlFor="chat-input">Message</label>
        <textarea
          id="chat-input"
          ref={taRef}
          className="composer-input"
          rows={1}
          placeholder={image ? 'What would you like to know about this image?' : 'Ask about Synchronik ERP…'}
          value={value}
          maxLength={MAX_LEN}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
          }}
        />

        {busy ? (
          <button type="button" className="send-btn stop" aria-label="Stop generating" onClick={onStop}>
            <Icon name="stop" size={16} />
          </button>
        ) : (
          <button type="button" className="send-btn" aria-label="Send message" disabled={!canSend} onClick={submit}>
            <Icon name="send" size={16} />
          </button>
        )}
      </div>
      {value.length > MAX_LEN * 0.9 && (
        <div className="composer-hint">
          <span className={value.length >= MAX_LEN ? 'warn' : ''}>{value.length}/{MAX_LEN} characters</span>
        </div>
      )}
    </div>
  )
})

export default ChatInput
