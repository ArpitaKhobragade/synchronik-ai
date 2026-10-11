import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamChat, ApiError } from '../api/client.js'

let seq = 0
const newKey = (p) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`
const nowIso = () => new Date().toISOString()

/** Normalise a stored Message from GET /api/conversations/{id}. */
function fromServer(m) {
  // A stored "Attached <file>" notice is shown the same way as during the upload: as an event row.
  if (m.role === 'user' && m.attachment && m.attachment.kind !== 'image') {
    return { key: `s-${m.id}`, id: m.id, role: 'event', kind: 'attachment', name: m.attachment.name,
      status: 'done', created_at: m.created_at }
  }
  return {
    key: `s-${m.id}`,
    id: m.id,
    role: m.role,
    content: m.content || '',
    created_at: m.created_at,
    sources: m.sources || [],
    confidence: m.confidence || null,
    details: m.metadata || null,
    feedback: m.feedback || null,
    attachment: m.attachment || null,
    status: 'done',
  }
}

/** Map a ChatResponse onto assistant-message fields. */
function fromResponse(r) {
  const meta = r.metadata || {}
  return {
    id: r.message_id,
    content: r.answer ?? r.response ?? '',
    sources: r.sources || [],
    confidence: r.confidence || null,
    grounded: r.grounded,
    details: {
      intent: r.intent,
      rewritten_query: r.rewritten_query,
      retrieval_count: r.retrieval_count,
      latency_ms: r.latency_ms,
      ...meta,
    },
    status: 'done',
    stage: null,
    error: null,
    created_at: nowIso(),
  }
}

const EMPTY = { id: null, title: null, messages: [] }

/**
 * Conversation state + all chat actions.
 * conversationId comes from the URL; onConversationId(id) is called when the server creates one.
 */
export function useChat({ conversationId, onConversationId, onActivity }) {
  const [data, setData] = useState(EMPTY)
  const [loadError, setLoadError] = useState(null)
  const [reloadTick, setReloadTick] = useState(0)
  const dataIdRef = useRef(null)
  const ctrlRef = useRef(null)
  const cbRef = useRef({ onConversationId, onActivity })
  const routeIdRef = useRef(conversationId)

  useEffect(() => { cbRef.current = { onConversationId, onActivity } }, [onConversationId, onActivity])
  useEffect(() => { routeIdRef.current = conversationId }, [conversationId])
  useEffect(() => () => { if (ctrlRef.current) ctrlRef.current.abort() }, [])

  // Load a conversation when the URL points at one we don't already hold.
  useEffect(() => {
    if (conversationId === dataIdRef.current) return
    if (ctrlRef.current) { ctrlRef.current.abort(); ctrlRef.current = null }
    if (!conversationId) return
    const ctrl = new AbortController()
    api.getConversation(conversationId, ctrl.signal)
      .then((conv) => {
        dataIdRef.current = conversationId
        setLoadError(null)
        setData({ id: conversationId, title: conv.title, messages: (conv.messages || []).map(fromServer) })
      })
      .catch((e) => { if (e.name !== 'AbortError') setLoadError({ id: conversationId, error: e }) })
    return () => ctrl.abort()
  }, [conversationId, reloadTick])

  /** Re-attempt loading the current conversation after a failed load (e.g. a 5xx). */
  const reload = useCallback(() => {
    setLoadError(null)
    setReloadTick((t) => t + 1)
  }, [])

  const visible = data.id === conversationId || (!conversationId && data.id === null) ? data : EMPTY
  const loading = Boolean(conversationId) && data.id !== conversationId && !(loadError && loadError.id === conversationId)
  const error = loadError && loadError.id === conversationId ? loadError.error : null

  const reset = useCallback(() => {
    if (ctrlRef.current) { ctrlRef.current.abort(); ctrlRef.current = null }
    dataIdRef.current = null
    setData(EMPTY)
  }, [])

  const adopt = useCallback((cid) => {
    if (!cid || dataIdRef.current === cid) return
    dataIdRef.current = cid
    setData((d) => ({ ...d, id: cid }))
    cbRef.current.onConversationId && cbRef.current.onConversationId(cid)
  }, [])

  const patch = useCallback((key, p) => {
    setData((d) => ({ ...d, messages: d.messages.map((m) => (m.key === key ? { ...m, ...(typeof p === 'function' ? p(m) : p) } : m)) }))
  }, [])

  // Appending always targets the conversation in the URL; a stale buffer is replaced.
  const append = useCallback((...msgs) => {
    const rid = routeIdRef.current || null
    dataIdRef.current = rid
    setData((d) => (d.id === rid ? { ...d, messages: [...d.messages, ...msgs] } : { id: rid, title: null, messages: msgs }))
  }, [])

  const fail = useCallback((key, e) => {
    if (e && e.name === 'AbortError') return
    const err = e instanceof ApiError ? e : new ApiError('internal_error', String(e && e.message))
    patch(key, { status: 'error', stage: null, error: { code: err.code, message: err.message } })
  }, [patch])

  const finish = useCallback((key, response) => {
    patch(key, fromResponse(response))
    adopt(response.conversation_id || response.session_id)
    cbRef.current.onActivity && cbRef.current.onActivity()
  }, [patch, adopt])

  /** Execute (or re-execute) the request attached to an assistant message. */
  const run = useCallback(async (key, req, streaming) => {
    if (ctrlRef.current) ctrlRef.current.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    const cid = dataIdRef.current
    const done = () => { if (ctrlRef.current === ctrl) ctrlRef.current = null }

    try {
      if (req.kind === 'image') {
        patch(key, { stage: 'uploading', progress: 0 })
        const r = await api.imageChat(req.file, req.text, cid, {
          signal: ctrl.signal,
          onProgress: (p) => patch(key, { progress: p, stage: p >= 1 ? 'analyzing' : 'uploading' }),
        })
        finish(key, r)
        return
      }
      const regen = req.kind === 'regenerate'
      const regenBody = regen ? (req.text ? { conversation_id: cid, message: req.text } : { conversation_id: cid }) : null
      if (streaming) {
        let final = null
        let streamErr = null
        const body = regen ? regenBody : (cid ? { message: req.text, conversation_id: cid } : { message: req.text })
        try {
          await streamChat(body, {
            onStatus: (s) => patch(key, (m) => (m.status === 'pending' ? { stage: s.stage, stageLabel: s.label } : {})),
            onMeta: (m) => {
              adopt(m.conversation_id)
              patch(key, { sources: m.sources || [], confidence: m.confidence || null, grounded: m.grounded,
                details: { intent: m.intent, rewritten_query: m.rewritten_query, retrieval_count: m.retrieval_count } })
            },
            onToken: (t) => patch(key, (m) => ({ status: 'streaming', stage: null, content: m.content + (t.text || '') })),
            onDone: (r) => { final = r },
            onError: (e) => { streamErr = new ApiError(e.code || 'internal_error', e.message) },
          }, ctrl.signal, regen ? '/api/chat/regenerate/stream' : '/api/chat/stream')
        } catch (e) {
          if (e.name === 'AbortError') throw e
          // An HTTP error (4xx/5xx) is a real answer from the server; only a missing stream falls back.
          if (!e.beforeAnyEvent || e.status >= 400) throw e
          // Stream endpoint unreachable before any event: fall back to the plain endpoint.
          finish(key, regen ? await api.regenerate(regenBody, ctrl.signal) : await api.chat(req.text, cid, ctrl.signal))
          return
        }
        if (streamErr) throw streamErr
        if (final) { finish(key, final); return }
        throw new ApiError('network_error', 'The stream ended unexpectedly')
      }
      finish(key, regen ? await api.regenerate(regenBody, ctrl.signal) : await api.chat(req.text, cid, ctrl.signal))
    } catch (e) {
      fail(key, e)
    } finally {
      done()
    }
  }, [patch, finish, fail, adopt])

  const send = useCallback((text, { streaming = true } = {}) => {
    const user = { key: newKey('u'), role: 'user', content: text, created_at: nowIso(), status: 'done' }
    const req = { kind: 'text', text }
    const asst = { key: newKey('a'), role: 'assistant', content: '', status: 'pending', stage: 'understanding', created_at: nowIso(), request: req, sources: [] }
    append(user, asst)
    run(asst.key, req, streaming)
  }, [append, run])

  const sendImage = useCallback((file, question, previewUrl) => {
    const user = { key: newKey('u'), role: 'user', content: question, created_at: nowIso(), status: 'done', attachment: { name: file.name, kind: 'image', previewUrl } }
    const req = { kind: 'image', text: question, file }
    const asst = { key: newKey('a'), role: 'assistant', content: '', status: 'pending', stage: 'uploading', created_at: nowIso(), request: req, sources: [] }
    append(user, asst)
    run(asst.key, req, false)
  }, [append, run])

  const retry = useCallback((key, { streaming = true } = {}) => {
    const msg = data.messages.find((m) => m.key === key)
    if (!msg || !msg.request) return
    // Re-sending a text question the server may already hold would duplicate it in history, so the
    // last exchange is retried through regenerate, which replaces it (or answers fresh if it was never stored).
    const last = [...data.messages].reverse().find((m) => m.role === 'assistant')
    const req = msg.request.kind === 'text' && dataIdRef.current && last && last.key === key
      ? { kind: 'regenerate', text: msg.request.text }
      : msg.request
    patch(key, { status: 'pending', stage: req.kind === 'image' ? 'uploading' : 'understanding', error: null, content: '', sources: [], confidence: null, details: null, request: req })
    run(key, req, streaming)
  }, [data.messages, patch, run])

  const regenerate = useCallback((key) => {
    const msg = data.messages.find((m) => m.key === key)
    if (!msg || !dataIdRef.current) return
    const req = { kind: 'regenerate' }
    patch(key, { status: 'pending', stage: 'understanding', error: null, content: '', sources: [], confidence: null, details: null, feedback: null, request: req })
    run(key, req, true)
  }, [data.messages, patch, run])

  const stop = useCallback(() => {
    if (ctrlRef.current) { ctrlRef.current.abort(); ctrlRef.current = null }
    setData((d) => ({
      ...d,
      messages: d.messages.map((m) => (m.status === 'pending' || m.status === 'streaming' ? { ...m, status: 'stopped', stage: null } : m)),
    }))
  }, [])

  const attachDocument = useCallback(async (file) => {
    const key = newKey('e')
    append({ key, role: 'event', kind: 'attachment', name: file.name, status: 'uploading', progress: 0, created_at: nowIso() })
    try {
      const r = await api.attach(file, dataIdRef.current, {
        onProgress: (p) => patch(key, { progress: p, status: p >= 1 ? 'processing' : 'uploading' }),
      })
      patch(key, { status: 'done', chunks: r && r.chunks, serverMessage: r && r.message })
      adopt(r && r.conversation_id)
      cbRef.current.onActivity && cbRef.current.onActivity()
      return true
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('internal_error')
      patch(key, { status: 'error', error: { code: err.code, message: err.message } })
      return false
    }
  }, [append, patch, adopt])

  const dismiss = useCallback((key) => setData((d) => ({ ...d, messages: d.messages.filter((m) => m.key !== key) })), [])

  const setFeedback = useCallback((key, value) => patch(key, { feedback: value }), [patch])

  const busy = visible.messages.some((m) => m.status === 'pending' || m.status === 'streaming')

  return {
    messages: visible.messages, title: visible.title, loading, error, busy,
    send, sendImage, retry, regenerate, stop, attachDocument, dismiss, setFeedback, reset, reload,
  }
}
