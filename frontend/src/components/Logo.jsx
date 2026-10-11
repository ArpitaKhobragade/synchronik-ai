/** Monogram mark: an ink tile with the "S" stroke and a Synchronik-blue point (the brand "R" colour). */
export function LogoMark({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false" className="logo-mark">
      <rect width="32" height="32" rx="8" style={{ fill: 'var(--action)' }} />
      <path d="M21.5 10.5c-1.2-1.3-3-2-5.2-2-3.2 0-5.3 1.7-5.3 4.1 0 5.4 10.8 3 10.8 8.2 0 2.5-2.3 4.2-5.6 4.2-2.4 0-4.4-.9-5.7-2.4"
        fill="none" style={{ stroke: 'var(--action-fg)' }} strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="23.5" cy="23.5" r="2.2" fill="#3b82f6" />
    </svg>
  )
}

/** Brand wordmark "SyNchRoniK" with the blue R. */
export function BrandWord() {
  return (
    <span className="brand-word" aria-label="Synchronik">
      SyNch<span className="brand-r">R</span>oniK
    </span>
  )
}

export default function Logo({ compact = false }) {
  return (
    <span className="logo">
      <LogoMark />
      {!compact && (
        <span className="logo-text">
          <span className="logo-title">Synchronik <span className="logo-ai">AI</span></span>
          <span className="logo-sub">ERP Knowledge Assistant</span>
        </span>
      )}
    </span>
  )
}
