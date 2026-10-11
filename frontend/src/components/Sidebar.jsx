import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useDebounced } from '../hooks/useDebounced.js'
import { useToast } from '../hooks/useToast.js'
import { friendlyError } from '../lib/errors.js'
import Icon from './Icon.jsx'
import Logo, { BrandWord } from './Logo.jsx'
import { ConfirmDialog } from './Modal.jsx'

function ConversationItem({ conv, active, onOpen, onRenamed, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conv.title || '')
  const toast = useToast()

  const commit = async () => {
    const title = draft.trim()
    setEditing(false)
    if (!title || title === conv.title) return
    try {
      await api.renameConversation(conv.id, title)
      onRenamed()
    } catch (e) {
      toast.push({ tone: 'error', message: friendlyError(e) })
    }
  }

  if (editing) {
    return (
      <li className="conv-item editing">
        <input
          className="conv-rename"
          value={draft}
          aria-label="Conversation title"
          autoComplete="off"
          autoFocus
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit() }
            if (e.key === 'Escape') { e.stopPropagation(); setEditing(false); setDraft(conv.title || '') }
          }}
        />
      </li>
    )
  }

  return (
    <li className={`conv-item ${active ? 'active' : ''}`}>
      <button type="button" className="conv-open" onClick={() => onOpen(conv.id)} aria-current={active ? 'page' : undefined}>
        <span className="conv-title">{conv.title || 'Untitled conversation'}</span>
        {conv.match && <span className="conv-match">{conv.match}</span>}
      </button>
      <span className="conv-actions">
        <button type="button" className="icon-btn icon-btn-sm" aria-label={`Rename “${conv.title || 'conversation'}”`} onClick={() => { setDraft(conv.title || ''); setEditing(true) }}>
          <Icon name="edit" size={14} />
        </button>
        <button type="button" className="icon-btn icon-btn-sm icon-btn-danger" aria-label={`Delete “${conv.title || 'conversation'}”`} onClick={() => onDelete(conv)}>
          <Icon name="trash" size={14} />
        </button>
      </span>
    </li>
  )
}

export default function Sidebar({
  page, activeId, refreshKey, onRefresh, onNewChat, onOpenConversation, onDeleted, onNavigate, onOpenSettings,
  open, onClose, collapsed, onToggleCollapsed, searchRef,
}) {
  const [query, setQuery] = useState('')
  const q = useDebounced(query.trim(), 300)
  const [result, setResult] = useState({ key: null, items: [], error: null })
  const [confirm, setConfirm] = useState(null)
  const toast = useToast()
  const asideRef = useRef(null)
  const reqKey = `${q}::${refreshKey}`

  useEffect(() => {
    const ctrl = new AbortController()
    api.listConversations(q, ctrl.signal)
      .then((items) => setResult({ key: reqKey, items: Array.isArray(items) ? items : [], error: null }))
      .catch((e) => { if (e.name !== 'AbortError') setResult({ key: reqKey, items: [], error: e }) })
    return () => ctrl.abort()
  }, [q, reqKey])

  // Esc closes the mobile drawer.
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const loading = result.key !== reqKey
  const doDelete = async () => {
    const conv = confirm
    setConfirm(null)
    try {
      await api.deleteConversation(conv.id)
      toast.push({ tone: 'success', message: 'Conversation deleted.' })
      onDeleted(conv.id)
      onRefresh()
    } catch (e) {
      toast.push({ tone: 'error', message: friendlyError(e) })
    }
  }

  const nav = [
    { page: 'chat', label: 'Assistant', icon: 'chat', path: activeId ? `/chat/${encodeURIComponent(activeId)}` : '/chat' },
    { page: 'knowledge', label: 'Knowledge Base', icon: 'book', path: '/knowledge' },
  ]

  return (
    <>
      {open && <div className="drawer-scrim" onClick={onClose} aria-hidden="true" />}
      <aside ref={asideRef} className={`sidebar ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`} aria-label="Sidebar">
        <div className="sb-top">
          <a href="#/chat" className="sb-logo" aria-label="Synchronik AI home" onClick={onClose}>
            <Logo compact={collapsed} />
          </a>
          <button type="button" className="icon-btn sb-collapse" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={onToggleCollapsed}>
            <Icon name={collapsed ? 'chevronRight' : 'chevronLeft'} />
          </button>
          <button type="button" className="icon-btn sb-close" aria-label="Close menu" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>

        <button type="button" className="btn btn-primary sb-new" onClick={onNewChat} title="New chat (Ctrl+Shift+O)">
          <Icon name="plus" size={16} />
          <span className="sb-label">New chat</span>
        </button>

        <nav className="sb-nav" aria-label="Main">
          {nav.map((n) => (
            <button key={n.page} type="button" className={`sb-link ${page === n.page ? 'active' : ''}`}
              aria-current={page === n.page ? 'page' : undefined} onClick={() => onNavigate(n.path)} title={n.label}>
              <Icon name={n.icon} />
              <span className="sb-label">{n.label}</span>
            </button>
          ))}
        </nav>

        <div className="sb-section">
          <div className="sb-search">
            <Icon name="search" size={15} />
            <input
              ref={searchRef}
              type="search"
              autoComplete="off"
              spellCheck={false}
              placeholder="Search conversations"
              aria-label="Search conversations (Ctrl+K)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape' && query) { e.stopPropagation(); setQuery('') } }}
            />
            <kbd className="sb-kbd" aria-hidden="true">Ctrl K</kbd>
          </div>
          <h2 className="sb-heading">{q ? 'Search results' : 'Recent'}</h2>
          <div className="sb-list-wrap">
            {loading && result.items.length === 0 && (
              <ul className="conv-list" aria-hidden="true">
                {[0, 1, 2].map((i) => <li key={i} className="conv-skeleton" />)}
              </ul>
            )}
            {!loading && result.error && (
              <p className="sb-empty">
                Couldn’t load conversations.{' '}
                <button type="button" className="btn-link" onClick={onRefresh}>Retry</button>
              </p>
            )}
            {!loading && !result.error && result.items.length === 0 && (
              <p className="sb-empty">{q ? `No conversations match “${q}”.` : 'No conversations yet. Ask your first question!'}</p>
            )}
            {result.items.length > 0 && (
              <ul className="conv-list" aria-busy={loading}>
                {result.items.map((c) => (
                  <ConversationItem key={c.id} conv={c} active={c.id === activeId}
                    onOpen={onOpenConversation} onRenamed={onRefresh} onDelete={setConfirm} />
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="sb-bottom">
          <button type="button" className="sb-link" onClick={onOpenSettings} title="Settings">
            <Icon name="settings" />
            <span className="sb-label">Settings</span>
          </button>
          <div className="sb-contact">
            <BrandWord />
            <div className="sb-contact-links">
              <a href="tel:+919225248455" aria-label="Call Synchronik"><Icon name="phone" size={15} /></a>
              <a href="https://wa.me/919225248455" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp Synchronik"><Icon name="whatsapp" size={15} /></a>
              <a href="https://synchronik.co.in/contact.html#demo" target="_blank" rel="noopener noreferrer" className="sb-demo">Book a demo</a>
            </div>
          </div>
        </div>
      </aside>

      {confirm && (
        <ConfirmDialog
          title="Delete conversation?"
          message={`“${confirm.title || 'Untitled conversation'}” and its messages will be permanently deleted.`}
          confirmLabel="Delete"
          danger
          onConfirm={doDelete}
          onCancel={() => setConfirm(null)}
        />
      )}
    </>
  )
}
