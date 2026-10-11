import { STAGES, stageLabel } from '../lib/stages.js'

export default function ThinkingIndicator({ stage, label, progress }) {
  const idx = STAGES.findIndex((s) => s.key === stage)
  const text = stageLabel(stage, label)
  return (
    <div className="thinking">
      <span className="thinking-pulse" aria-hidden="true"><i /><i /><i /></span>
      <span className="thinking-label">
        {text}
        {stage === 'uploading' && typeof progress === 'number' && ` ${Math.round(progress * 100)}%`}
      </span>
      {idx >= 0 && (
        <ol className="stage-steps" aria-hidden="true">
          {STAGES.map((s, i) => <li key={s.key} className={i < idx ? 'done' : i === idx ? 'current' : ''} />)}
        </ol>
      )}
    </div>
  )
}
