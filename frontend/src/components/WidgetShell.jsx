import { useEffect, useState } from 'react'
import ChatView from './ChatView.jsx'
import Icon from './Icon.jsx'
import { BrandWord, LogoMark } from './Logo.jsx'

/** Floating widget mode (?mode=widget) — reuses the same ChatView. */
export default function WidgetShell({ prefs }) {
  const [open, setOpen] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const newChat = () => { setConversationId(null); setNonce((n) => n + 1) }

  return (
    <div className="widget-root">
      {open && (
        <section className="widget-panel" role="dialog" aria-label="Synchronik AI assistant">
          <header className="widget-head">
            <LogoMark size={30} />
            <div className="widget-head-text">
              <strong>Synchronik AI</strong>
              <span><BrandWord /> ERP assistant</span>
            </div>
            <div className="widget-head-actions">
              <a className="icon-btn" href="tel:+919225248455" aria-label="Call Synchronik"><Icon name="phone" size={16} /></a>
              <a className="icon-btn" href="https://wa.me/919225248455" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp Synchronik"><Icon name="whatsapp" size={16} /></a>
              <button type="button" className="icon-btn" aria-label="New chat" onClick={newChat}><Icon name="plus" size={16} /></button>
              <button type="button" className="icon-btn" aria-label="Close assistant" onClick={() => setOpen(false)}><Icon name="close" size={16} /></button>
            </div>
          </header>
          <ChatView key={nonce} compact conversationId={conversationId} onConversationId={setConversationId} prefs={prefs} onNewChat={newChat} />
          <footer className="widget-foot">
            <a href="https://synchronik.co.in/contact.html#demo" target="_blank" rel="noopener noreferrer">Book a free demo</a>
          </footer>
        </section>
      )}
      <button type="button" className="widget-fab" aria-label={open ? 'Close assistant' : 'Open Synchronik AI assistant'} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <Icon name="close" size={22} /> : <LogoMark size={34} />}
      </button>
    </div>
  )
}
