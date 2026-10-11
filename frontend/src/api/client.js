// Synchronik AI API client. Endpoints and error envelope: docs/API.md.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(code, message, status = 0, requestId = null) {
    super(message || code)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.requestId = requestId
  }
}

const STATUS_CODES = {
  401: 'unauthorized', 404: 'not_found', 408: 'timeout', 413: 'file_too_large', 415: 'unsupported_file',
  422: 'validation_error', 429: 'rate_limited', 503: 'backend_unavailable', 504: 'timeout',
}

async function toApiError(res) {
  let body = null
  try { body = await res.json() } catch { /* non-JSON body */ }
  const err = body && body.error
  return new ApiError(
    (err && err.code) || STATUS_CODES[res.status] || 'internal_error',
    (err && err.message) || res.statusText,
    res.status,
    (err && err.request_id) || res.headers.get('X-Request-ID'),
  )
}

function buildHeaders(adminKey, json) {
  const h = {}
  if (json) h['Content-Type'] = 'application/json'
  if (adminKey) h['X-Admin-Key'] = adminKey
  return h
}

export async function request(path, { method = 'GET', body, adminKey, signal, raw = false } = {}) {
  let res
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: buildHeaders(adminKey, body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError('network_error', 'Network error', 0)
  }
  if (!res.ok) throw await toApiError(res)
  if (raw) return res
  if (res.status === 204) return null
  const text = await res.text()
  try {
    return text ? JSON.parse(text) : null
  } catch {
    throw new ApiError('malformed_response', 'Invalid response from server', res.status)
  }
}

/** Multipart upload with progress via XMLHttpRequest (fetch has no upload progress). */
export function upload(path, formData, { adminKey, onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', API_BASE + path)
    if (adminKey) xhr.setRequestHeader('X-Admin-Key', adminKey)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
    xhr.upload.onload = () => { if (onProgress) onProgress(1) }
    xhr.onload = () => {
      let body = null
      try { body = xhr.responseText ? JSON.parse(xhr.responseText) : null } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) { resolve(body); return }
      const err = body && body.error
      reject(new ApiError((err && err.code) || STATUS_CODES[xhr.status] || 'internal_error', err && err.message, xhr.status, err && err.request_id))
    }
    xhr.onerror = () => reject(new ApiError('network_error', 'Network error', 0))
    xhr.ontimeout = () => reject(new ApiError('timeout', 'Request timed out', 0))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    if (signal) signal.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(formData)
  })
}

const EVENT_HANDLERS = { status: 'onStatus', meta: 'onMeta', token: 'onToken', done: 'onDone', error: 'onError' }

/**
 * POST /api/chat/stream (or /api/chat/regenerate/stream) — SSE parsed from a fetch ReadableStream.
 * handlers: { onStatus, onMeta, onToken, onDone, onError }
 * Errors thrown carry `beforeAnyEvent` so the caller can fall back to POST /api/chat.
 */
export async function streamChat(body, handlers, signal, path = '/api/chat/stream') {
  let res
  try {
    res = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    const err = new ApiError('network_error', 'Network error', 0)
    err.beforeAnyEvent = true
    throw err
  }
  if (!res.ok || !res.body) {
    const err = res.ok ? new ApiError('internal_error', 'Streaming not supported', res.status) : await toApiError(res)
    err.beforeAnyEvent = true
    throw err
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let gotEvent = false
  const dispatch = (block) => {
    let event = 'message'
    const data = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) return
    let payload
    try { payload = JSON.parse(data.join('\n')) } catch { return }
    gotEvent = true
    const fn = handlers[EVENT_HANDLERS[event]]
    if (fn) fn(payload)
  }
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n')
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        dispatch(buffer.slice(0, idx))
        buffer = buffer.slice(idx + 2)
      }
    }
    if (buffer.trim()) dispatch(buffer)
  } catch (e) {
    if (e.name === 'AbortError') throw e
    const err = new ApiError('network_error', 'Connection lost while streaming', 0)
    err.beforeAnyEvent = !gotEvent
    throw err
  }
  return gotEvent
}

const enc = encodeURIComponent

export const api = {
  /** Health returns a JSON body even with HTTP 503 ("unhealthy"), so parse it regardless of status. */
  health: async (signal) => {
    let res
    try {
      res = await fetch(API_BASE + '/api/health', { signal })
    } catch (e) {
      if (e.name === 'AbortError') throw e
      throw new ApiError('network_error', 'Network error', 0)
    }
    let body = null
    try { body = await res.json() } catch { /* non-JSON body */ }
    if (body && typeof body.status === 'string') return body
    throw new ApiError(res.ok ? 'malformed_response' : STATUS_CODES[res.status] || 'internal_error', 'Invalid health response', res.status)
  },
  chat: (message, conversationId, signal) =>
    request('/api/chat', { method: 'POST', body: conversationId ? { message, conversation_id: conversationId } : { message }, signal }),
  /** body: { conversation_id, message? } — `message` makes it a safe retry (see RegenerateRequest). */
  regenerate: (body, signal) => request('/api/chat/regenerate', { method: 'POST', body, signal }),
  imageChat: (file, question, conversationId, opts) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('question', question)
    if (conversationId) fd.append('conversation_id', conversationId)
    return upload('/api/chat/image', fd, opts)
  },
  attach: (file, conversationId, opts) => {
    const fd = new FormData()
    fd.append('file', file)
    if (conversationId) fd.append('conversation_id', conversationId)
    return upload('/api/chat/attachments', fd, opts)
  },
  listConversations: (q, signal) => request('/api/conversations' + (q ? `?q=${enc(q)}` : ''), { signal }),
  getConversation: (id, signal) => request(`/api/conversations/${enc(id)}`, { signal }),
  renameConversation: (id, title) => request(`/api/conversations/${enc(id)}`, { method: 'PATCH', body: { title } }),
  deleteConversation: (id) => request(`/api/conversations/${enc(id)}`, { method: 'DELETE' }),
  exportConversation: (id) => request(`/api/conversations/${enc(id)}/export?format=markdown`, { raw: true }),
  feedback: (body) => request('/api/feedback', { method: 'POST', body }),
  documents: (signal) => request('/api/documents', { signal }),
  uploadDocument: (file, adminKey, onProgress) => {
    const fd = new FormData()
    fd.append('file', file)
    return upload('/api/documents', fd, { adminKey, onProgress })
  },
  deleteDocument: (id, adminKey) => request(`/api/documents/${enc(id)}`, { method: 'DELETE', adminKey }),
  reprocessDocument: (id, adminKey) => request(`/api/documents/${enc(id)}/reprocess`, { method: 'POST', adminKey }),
  verifyAdmin: (adminKey) => request('/api/admin/verify', { method: 'POST', adminKey }),
  stats: (adminKey, signal) => request('/api/admin/stats', { adminKey, signal }),
  reindex: (adminKey) => request('/api/admin/reindex', { method: 'POST', adminKey }),
  crawl: (source, adminKey) => request('/api/admin/crawl', { method: 'POST', body: { source }, adminKey }),
  jobs: (adminKey, signal) => request('/api/admin/jobs', { adminKey, signal }),
}
