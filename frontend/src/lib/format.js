const STAGE_NAMES = {
  understanding_ms: 'Query understanding', embed_ms: 'Embedding', semantic_ms: 'Semantic search',
  keyword_ms: 'Keyword search', fusion_ms: 'Result fusion', rerank_ms: 'Reranking', context_ms: 'Context assembly',
  llm_first_token_ms: 'AI model: first token', llm_ms: 'AI model: full answer', total_ms: 'Total',
}
/** Human label for a per-stage timing key such as `semantic_ms`. */
export function stageName(key) {
  if (STAGE_NAMES[key]) return STAGE_NAMES[key]
  const s = String(key).replace(/_ms$/, '').replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// The server stores UTC; SQLite returns it without an offset, which browsers would read as local time.
const NO_OFFSET = /T[\d:.]+$/

const valid = (iso) => {
  if (!iso) return null
  const d = new Date(typeof iso === 'string' && NO_OFFSET.test(iso) ? `${iso}Z` : iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatTime(iso) {
  const d = valid(iso)
  return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
}

export function formatDateTime(iso) {
  const d = valid(iso)
  return d ? d.toLocaleString([], { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
}

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
export const pct = (v, digits = 0) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : '—')
export const ms = (v) => (isNum(v) ? (v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`) : '—')
export const num = (v) => (isNum(v) ? v.toLocaleString() : '—')

export function bytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const SOURCE_TYPE_LABEL = { website: 'Website', help_portal: 'Help portal', curated: 'Synchronik FAQ', upload: 'Uploaded doc', attachment: 'Attachment' }
