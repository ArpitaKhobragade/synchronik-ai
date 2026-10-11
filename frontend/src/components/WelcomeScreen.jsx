import Icon from './Icon.jsx'
import { LogoMark } from './Logo.jsx'

// One real question per ERP module the help portal documents.
const SUGGESTED_PROMPTS = [
  { module: 'Attendance', text: 'How does attendance work?' },
  { module: 'Course registration', text: 'How do I configure course registration?' },
  { module: 'OBE', text: 'Explain the OBE workflow' },
  { module: 'Examinations', text: 'How can I generate examination reports?' },
  { module: 'Library', text: 'How does the library module work?' },
]

export default function WelcomeScreen({ onPick, disabled, compact = false }) {
  return (
    <section className={`welcome ${compact ? 'welcome-compact' : ''}`} aria-labelledby="welcome-title">
      <LogoMark size={compact ? 32 : 40} />
      <h2 id="welcome-title" className="welcome-title">Ask about Synchronik ERP</h2>
      <p className="welcome-sub">
        Ask anything about Synchronik and its ERP. Answers from the help portal and the documents you attach show
        their sources underneath.
      </p>
      <ul className="prompt-index" aria-label="Suggested questions">
        {SUGGESTED_PROMPTS.map((p) => (
          <li key={p.text}>
            <button type="button" className="prompt-row" onClick={() => onPick(p.text)} disabled={disabled}>
              <span className="prompt-module">{p.module}</span>
              <span className="prompt-q">{p.text}</span>
              <span className="prompt-go" aria-hidden="true"><Icon name="send" size={14} /></span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
