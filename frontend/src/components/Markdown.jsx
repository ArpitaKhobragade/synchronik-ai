import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { stripCitations } from '../lib/citations.js'

function Markdown({ text }) {
  const components = {
    a({ href = '', children }) {
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
    table({ children }) {
      return <div className="md-table-wrap"><table>{children}</table></div>
    },
  }
  // react-markdown never renders raw HTML unless rehype-raw is added — keep it that way.
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {stripCitations(text)}
      </ReactMarkdown>
    </div>
  )
}

export default memo(Markdown)
