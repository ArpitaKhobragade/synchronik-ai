import { useCallback, useEffect, useRef, useState } from 'react'
import ChatHeader from './components/ChatHeader.jsx'
import ChatView from './components/ChatView.jsx'
import Icon from './components/Icon.jsx'
import KnowledgeBase from './components/KnowledgeBase.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import Sidebar from './components/Sidebar.jsx'
import ToastProvider from './components/Toast.jsx'
import WidgetShell from './components/WidgetShell.jsx'
import { useHashRoute, navigate } from './hooks/useHashRoute.js'
import { readAdminKey, readLastConversation, usePrefs, writeAdminKey, writeLastConversation } from './hooks/usePrefs.js'

const isWidget = () => {
  try { return new URLSearchParams(window.location.search).get('mode') === 'widget' } catch { return false }
}

// Restore the last active conversation when the app opens on a bare URL.
if (!isWidget() && !window.location.hash) {
  const last = readLastConversation()
  if (last) window.history.replaceState(null, '', `#/chat/${encodeURIComponent(last)}`)
}

function FullApp({ prefs, onPrefs }) {
  const [route, go] = useHashRoute()
  const [adminKey, setAdminKeyState] = useState(readAdminKey)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [listVersion, setListVersion] = useState(0)
  const [chatNonce, setChatNonce] = useState(0)
  const [title, setTitle] = useState(null)
  const searchRef = useRef(null)
  const inputRef = useRef(null)
  const activeId = route.page === 'chat' ? route.id : null

  useEffect(() => { if (route.page === 'chat') writeLastConversation(route.id) }, [route.page, route.id])

  const setAdminKey = useCallback((k) => { writeAdminKey(k); setAdminKeyState(k) }, [])
  const refreshList = useCallback(() => setListVersion((v) => v + 1), [])
  const closeDrawer = useCallback(() => setDrawerOpen(false), [])

  const newChat = useCallback(() => {
    setChatNonce((n) => n + 1)
    setTitle(null)
    setDrawerOpen(false)
    navigate('/chat')
    setTimeout(() => inputRef.current && inputRef.current.focus(), 0)
  }, [])

  const onConversationId = useCallback((id) => { navigate(`/chat/${encodeURIComponent(id)}`, { replace: true }); refreshList() }, [refreshList])

  // Global shortcuts: Ctrl/Cmd+K → search, Ctrl/Cmd+Shift+O → new chat.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setDrawerOpen(true)
        setCollapsed(false)
        setTimeout(() => searchRef.current && searchRef.current.focus(), 0)
      } else if (mod && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault()
        newChat()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [newChat])

  return (
    <div className={`app ${collapsed ? 'sb-collapsed' : ''}`}>
      <a href="#main" className="skip-link" onClick={(e) => { e.preventDefault(); document.getElementById('main').focus() }}>Skip to content</a>
      <Sidebar
        page={route.page}
        activeId={activeId}
        refreshKey={listVersion}
        onRefresh={refreshList}
        onNewChat={newChat}
        onOpenConversation={(id) => { setDrawerOpen(false); go(`/chat/${encodeURIComponent(id)}`) }}
        onDeleted={(id) => { if (id === activeId) newChat() }}
        onNavigate={(p) => { setDrawerOpen(false); go(p) }}
        onOpenSettings={() => { setDrawerOpen(false); setSettingsOpen(true) }}
        open={drawerOpen}
        onClose={closeDrawer}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        searchRef={searchRef}
      />

      <main id="main" className="main" tabIndex={-1}>
        {route.page === 'chat' ? (
          <>
            <ChatHeader title={activeId ? title : null} conversationId={activeId} onMenu={() => setDrawerOpen(true)} />
            <ChatView
              key={chatNonce}
              conversationId={activeId}
              onConversationId={onConversationId}
              onActivity={refreshList}
              onTitle={setTitle}
              prefs={prefs}
              inputRef={inputRef}
              onNewChat={newChat}
            />
          </>
        ) : (
          <>
            <header className="chat-header page-topbar">
              <button type="button" className="icon-btn hamburger" aria-label="Open menu" onClick={() => setDrawerOpen(true)}><Icon name="menu" /></button>
              <span className="chat-title">Knowledge Base</span>
            </header>
            <div className="page-scroll">
              <KnowledgeBase adminKey={adminKey} onAdminKey={setAdminKey} />
            </div>
          </>
        )}
      </main>

      {settingsOpen && (
        <SettingsPanel prefs={prefs} onPrefs={onPrefs} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  )
}

export default function App() {
  const [prefs, setPrefs] = usePrefs()
  const [widget] = useState(isWidget)
  return (
    <ToastProvider>
      {widget ? <WidgetShell prefs={prefs} /> : <FullApp prefs={prefs} onPrefs={setPrefs} />}
    </ToastProvider>
  )
}
