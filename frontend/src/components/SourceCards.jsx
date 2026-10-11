import { useState } from 'react'
import { SOURCE_TYPE_LABEL } from '../lib/format.js'
import Icon from './Icon.jsx'

function SourceCard({ source }) {
  const [open, setOpen] = useState(false)
  const loc = [source.section, source.page != null ? `p. ${source.page}` : null].filter(Boolean).join(' · ')
  const name = source.title || 'Untitled source'
  return (
    <li className="source-card">
      <div className="source-head">
        <div className="source-main">
          <div className="source-title-row">
            {source.url ? (
              <a className="source-title" href={source.url} target="_blank" rel="noopener noreferrer">
                {source.title || 'Untitled source'} <Icon name="external" size={12} />
              </a>
            ) : (
              <span className="source-title">{source.title || 'Untitled source'}</span>
            )}
          </div>
          <div className="source-meta">
            <span className={`badge badge-type badge-${source.source_type}`}>{SOURCE_TYPE_LABEL[source.source_type] || source.source_type}</span>
            {loc && <span className="source-loc">{loc}</span>}
          </div>
        </div>
        {source.snippet && (
          <button type="button" className="icon-btn icon-btn-sm" aria-expanded={open}
            aria-label={open ? `Hide preview of ${name}` : `Preview ${name}`} onClick={() => setOpen((o) => !o)}>
            <Icon name="chevronDown" size={15} className={open ? 'rot-180' : ''} />
          </button>
        )}
      </div>
      {open && source.snippet && <blockquote className="source-snippet">{source.snippet}</blockquote>}
    </li>
  )
}

export default function SourceCards({ sources, msgKey }) {
  if (!sources || sources.length === 0) return null
  return (
    <section className="sources" aria-label="Sources">
      <h3 className="sources-title">Sources</h3>
      <ul className="source-list">
        {sources.map((s) => (
          <SourceCard key={`${msgKey}-${s.id}-${s.chunk_id}`} source={s} />
        ))}
      </ul>
    </section>
  )
}
