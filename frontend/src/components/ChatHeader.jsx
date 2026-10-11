import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../hooks/useToast.js'
import { friendlyError } from '../lib/errors.js'
import Icon from './Icon.jsx'

export default function ChatHeader({ title, conversationId, onMenu, children }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  const toast = useToast()

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [menuOpen])

  // Share a link that opens this conversation. Anyone who can reach this site and has the link can read it.
  const share = async () => {
    const url = `${window.location.origin}${window.location.pathname}#/chat/${encodeURIComponent(conversationId)}`
    const shareTitle = title || 'Synchronik AI conversation'
    if (navigator.share && window.matchMedia('(pointer: coarse)').matches) {
      try { await navigator.share({ title: shareTitle, url }); return } catch (e) { if (e && e.name === 'AbortError') return }
    }
    try {
      await navigator.clipboard.writeText(url)
      toast.push({ tone: 'success', message: 'Link copied. Anyone with the link can open this chat.' })
    } catch {
      toast.push({ tone: 'info', message: `Copy this link: ${url}`, duration: 12000 })
    }
  }

  const exportMarkdown = async () => {
    setMenuOpen(false)
    try {
      const res = await api.exportConversation(conversationId)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const safe = (title || 'conversation').replace(/[^\w-]+/g, '-').slice(0, 60)
      a.href = url
      a.download = `${safe || 'conversation'}.md`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      toast.push({ tone: 'error', message: friendlyError(e) })
    }
  }

  return (
    <header className="chat-header">
      <button type="button" className="icon-btn hamburger" aria-label="Open menu" onClick={onMenu}>
        <Icon name="menu" />
      </button>
      <h1 className="chat-title" title={title || 'New conversation'}>{title || 'New conversation'}</h1>
      <div className="chat-header-actions">
        {children}
        {conversationId && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={share} aria-label="Share chat">
            <Icon name="share" size={15} /> <span className="hide-sm">Share</span>
          </button>
        )}
        {conversationId && (
          <div className="menu-wrap" ref={menuRef}>
            <button type="button" className="btn btn-ghost btn-sm" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
              <Icon name="download" size={15} /> <span className="hide-sm">Export</span>
            </button>
            {menuOpen && (
              <div className="menu" role="menu">
                <button type="button" role="menuitem" className="menu-item" onClick={exportMarkdown}>
                  <Icon name="file" size={15} /> Markdown (.md)
                </button>
                <button type="button" role="menuitem" className="menu-item" onClick={() => { setMenuOpen(false); setTimeout(() => window.print(), 50) }}>
                  <Icon name="printer" size={15} /> Print / Save as PDF
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
