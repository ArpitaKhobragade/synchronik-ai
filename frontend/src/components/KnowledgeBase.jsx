import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useResource } from '../hooks/useResource.js'
import { useToast } from '../hooks/useToast.js'
import { friendlyError } from '../lib/errors.js'
import { DOC_ACCEPT, validateFile } from '../lib/files.js'
import { formatDateTime, num, SOURCE_TYPE_LABEL } from '../lib/format.js'
import AdminKeyForm from './AdminKeyForm.jsx'
import Icon from './Icon.jsx'
import { ConfirmDialog } from './Modal.jsx'

const ACTIVE = ['queued', 'running']

function StatusBadge({ status }) {
  return <span className={`badge badge-status status-${status}`}>{status}</span>
}

function StatsCards({ stats }) {
  if (!stats) return null
  const cards = [
    ['Documents', num(stats.documents)],
    ['Chunks', num(stats.chunks)],
    ['Embedded chunks', num(stats.embedded_chunks)],
    ['Index vectors', num(stats.index_vectors)],
    ['Last crawl', formatDateTime(stats.last_crawl_at), true],
    ['Last index build', formatDateTime(stats.last_index_at), true],
  ]
  return (
    <div className="kpi-grid">
      {cards.map(([k, v, isDate]) => (
        <div key={k} className={isDate ? 'kpi kpi-date' : 'kpi'}>
          <span className="kpi-label">{k}</span>
          <span className="kpi-value" title={isDate ? String(v) : undefined}>{v}</span>
        </div>
      ))}
    </div>
  )
}

function UploadZone({ adminKey, onUploaded }) {
  const [state, setState] = useState(null) // {name, progress, phase, error}
  const [over, setOver] = useState(false)
  const inputRef = useRef(null)

  const start = async (file) => {
    const err = validateFile(file, 'document')
    if (err) { setState({ name: file.name, phase: 'error', error: err }); return }
    setState({ name: file.name, progress: 0, phase: 'uploading' })
    try {
      const r = await api.uploadDocument(file, adminKey, (p) => setState((s) => ({ ...s, progress: p, phase: p >= 1 ? 'processing' : 'uploading' })))
      setState({ name: file.name, phase: 'done', chunks: r && r.chunks, message: r && r.message })
      onUploaded()
    } catch (e) {
      setState({ name: file.name, phase: 'error', error: friendlyError(e) })
    }
  }

  const busy = state && (state.phase === 'uploading' || state.phase === 'processing')
  return (
    <div
      className={`dropzone ${over ? 'over' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !busy) start(f) }}
    >
      <Icon name="upload" size={22} />
      <p><strong>Drop a PDF or DOCX here</strong> or{' '}
        <button type="button" className="btn-link" disabled={busy} onClick={() => inputRef.current && inputRef.current.click()}>browse</button> (≤ 20 MB)
      </p>
      <input ref={inputRef} type="file" accept={DOC_ACCEPT} hidden onChange={(e) => { const f = e.target.files[0]; e.target.value = ''; if (f) start(f) }} />
      {state && (
        <div className={`upload-state upload-${state.phase}`} role="status">
          <span className="file-name">{state.name}</span>
          {state.phase === 'uploading' && <><span className="progress"><span style={{ width: `${Math.round(state.progress * 100)}%` }} /></span><span>{Math.round(state.progress * 100)}%</span></>}
          {state.phase === 'processing' && <span><span className="spinner" aria-hidden="true" /> Processing…</span>}
          {state.phase === 'done' && <span><Icon name="check" size={14} /> {state.message || 'Document processed successfully'}{state.chunks != null ? ` · ${num(state.chunks)} chunks` : ''}</span>}
          {state.phase === 'error' && <span><Icon name="alert" size={14} /> {state.error}</span>}
        </div>
      )}
    </div>
  )
}

function JobsTable({ jobs }) {
  if (!jobs || jobs.length === 0) return <p className="empty">No jobs have run yet.</p>
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Job</th><th>Status</th><th>Detail</th><th>Started</th><th>Finished</th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.kind} <span className="muted">#{j.id}</span></td>
              <td><StatusBadge status={j.status} /></td>
              <td className="cell-wrap">{j.detail || '—'}</td>
              <td>{formatDateTime(j.started_at)}</td>
              <td>{formatDateTime(j.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function KnowledgeBase({ adminKey, onAdminKey }) {
  const toast = useToast()
  const docs = useResource(useCallback((s) => api.documents(s), []), 'docs')
  const stats = useResource(useCallback((s) => api.stats(adminKey, s), [adminKey]), adminKey || null)
  const [jobs, setJobs] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [crawlSource, setCrawlSource] = useState('all')
  const [busyIds, setBusyIds] = useState([])
  const reloadDocs = docs.reload
  const reloadStats = stats.reload

  const handleAuthError = useCallback((e) => {
    if (e.code === 'unauthorized') { onAdminKey(''); toast.push({ tone: 'error', message: 'Admin key rejected — please enter it again.' }) }
    else toast.push({ tone: 'error', message: friendlyError(e) })
  }, [onAdminKey, toast])

  // Jobs: initial load, then poll while any job is queued/running.
  const hasActive = Boolean(jobs && jobs.some((j) => ACTIVE.includes(j.status)))
  const prevActive = useRef(false)
  useEffect(() => {
    if (!adminKey) return
    let alive = true
    const load = () => api.jobs(adminKey).then((j) => { if (alive) setJobs(Array.isArray(j) ? j : []) }).catch(() => {})
    load()
    if (!hasActive) return () => { alive = false }
    const t = setInterval(load, 3000)
    return () => { alive = false; clearInterval(t) }
  }, [adminKey, hasActive])

  useEffect(() => {
    if (prevActive.current && !hasActive) { reloadDocs(); reloadStats() }
    prevActive.current = hasActive
  }, [hasActive, reloadDocs, reloadStats])

  const runJob = async (fn, label) => {
    try {
      const job = await fn()
      toast.push({ tone: 'success', message: `${label} started.` })
      if (job) setJobs((js) => [job, ...(js || []).filter((x) => x.id !== job.id)])
    } catch (e) { handleAuthError(e) }
  }

  const withBusy = async (id, fn) => {
    setBusyIds((b) => [...b, id])
    try { await fn() } finally { setBusyIds((b) => b.filter((x) => x !== id)) }
  }

  const doDelete = async () => {
    const d = confirm
    setConfirm(null)
    await withBusy(d.id, async () => {
      try {
        await api.deleteDocument(d.id, adminKey)
        toast.push({ tone: 'success', message: `“${d.title}” deleted.` })
        reloadDocs(); reloadStats()
      } catch (e) { handleAuthError(e) }
    })
  }

  const reprocess = (d) => withBusy(d.id, async () => {
    try {
      const r = await api.reprocessDocument(d.id, adminKey)
      toast.push({ tone: 'success', message: `Reprocessed “${d.title}”${r && r.chunks != null ? ` · ${r.chunks} chunks` : ''}.` })
      reloadDocs(); reloadStats()
    } catch (e) { handleAuthError(e) }
  })

  const list = Array.isArray(docs.data) ? docs.data : []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Knowledge Base</h1>
          <p className="muted">Documentation the assistant searches to ground its answers.</p>
        </div>
      </header>

      {adminKey ? (
        <section className="panel" aria-labelledby="kb-admin">
          <div className="panel-head">
            <h2 id="kb-admin"><Icon name="lock" size={16} /> Administration</h2>
            <div className="panel-actions">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => runJob(() => api.reindex(adminKey), 'Index rebuild')}>
                <Icon name="refresh" size={14} /> Rebuild index
              </button>
              <label className="sr-only" htmlFor="crawl-source">Crawl source</label>
              <select id="crawl-source" className="input input-sm" value={crawlSource} onChange={(e) => setCrawlSource(e.target.value)}>
                <option value="all">All sources</option>
                <option value="help_portal">Help portal</option>
                <option value="website">Website</option>
                <option value="curated">Synchronik FAQ</option>
              </select>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => runJob(() => api.crawl(crawlSource, adminKey), 'Crawl')}>
                <Icon name="globe" size={14} /> Trigger crawl
              </button>
            </div>
          </div>
          {stats.error ? <p className="inline-error">{friendlyError(stats.error)} <button type="button" className="btn-link" onClick={reloadStats}>Retry</button></p>
            : stats.data ? <StatsCards stats={stats.data} /> : <div className="skeleton-row" />}
          <UploadZone adminKey={adminKey} onUploaded={() => { reloadDocs(); reloadStats() }} />
          <h3 className="sub-head">Jobs {hasActive && <span className="muted small"><span className="spinner" aria-hidden="true" /> updating…</span>}</h3>
          {jobs === null ? <div className="skeleton-row" /> : <JobsTable jobs={jobs} />}
        </section>
      ) : (
        <section className="panel">
          <h2><Icon name="lock" size={16} /> Admin tools</h2>
          <p className="muted">Enter the admin key to upload, delete or reprocess documents, rebuild the index and trigger crawls.</p>
          <AdminKeyForm onVerified={onAdminKey} />
        </section>
      )}

      <section className="panel" aria-labelledby="kb-docs">
        <div className="panel-head">
          <h2 id="kb-docs">Documents {list.length > 0 && <span className="count">{list.length}</span>}</h2>
          <button type="button" className="icon-btn" aria-label="Refresh documents" onClick={reloadDocs}><Icon name="refresh" size={16} /></button>
        </div>
        {docs.error && <p className="inline-error" role="alert"><Icon name="alert" size={16} /> {friendlyError(docs.error)} <button type="button" className="btn-link" onClick={reloadDocs}>Retry</button></p>}
        {!docs.error && docs.loading && !docs.data && <div className="skeleton-row" />}
        {!docs.error && docs.data && list.length === 0 && <p className="empty">No documents in the knowledge base yet.</p>}
        {list.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Title</th><th>Type</th><th>Status</th><th className="num">Chunks</th><th>Updated</th>{adminKey && <th><span className="sr-only">Actions</span></th>}</tr>
              </thead>
              <tbody>
                {list.map((d) => (
                  <tr key={d.id}>
                    <td className="cell-wrap">
                      {d.source_url ? <a href={d.source_url} target="_blank" rel="noopener noreferrer">{d.title}</a> : d.title}
                      {d.status === 'failed' && d.error && <div className="field-error small">{d.error}</div>}
                    </td>
                    <td><span className={`badge badge-type badge-${d.source_type}`}>{SOURCE_TYPE_LABEL[d.source_type] || d.source_type}</span></td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="num">{num(d.chunk_count)}</td>
                    <td title={`Created ${formatDateTime(d.created_at)}${d.last_crawled_at ? ` · crawled ${formatDateTime(d.last_crawled_at)}` : ''}`}>{formatDateTime(d.updated_at)}</td>
                    {adminKey && (
                      <td className="row-actions">
                        <button type="button" className="icon-btn icon-btn-sm" aria-label={`Reprocess ${d.title}`} title="Reprocess" disabled={busyIds.includes(d.id)} onClick={() => reprocess(d)}><Icon name="refresh" size={14} /></button>
                        <button type="button" className="icon-btn icon-btn-sm icon-btn-danger" aria-label={`Delete ${d.title}`} title="Delete" disabled={busyIds.includes(d.id)} onClick={() => setConfirm(d)}><Icon name="trash" size={14} /></button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {confirm && (
        <ConfirmDialog title="Delete document?" danger confirmLabel="Delete"
          message={`“${confirm.title}” and its ${confirm.chunk_count != null ? `${num(confirm.chunk_count)} ` : ''}indexed chunks will be removed from the knowledge base.`}
          onConfirm={doDelete} onCancel={() => setConfirm(null)} />
      )}
    </div>
  )
}
