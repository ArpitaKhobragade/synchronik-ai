import Icon from './Icon.jsx'
import Modal from './Modal.jsx'

function Toggle({ id, label, hint, checked, onChange }) {
  return (
    <div className="setting-row">
      <div>
        <label htmlFor={id} className="setting-label">{label}</label>
        {hint && <p className="muted small">{hint}</p>}
      </div>
      <input id={id} type="checkbox" role="switch" className="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </div>
  )
}

// The admin key is entered on the Knowledge Base page, where it is needed; Settings holds only personal preferences.
export default function SettingsPanel({ prefs, onPrefs, onClose }) {
  return (
    <Modal title="Settings" onClose={onClose}>
      <section className="settings-section">
        <h3>Appearance</h3>
        <div className="segmented" role="radiogroup" aria-label="Theme">
          {[['system', 'System', 'settings'], ['light', 'Light', 'sun'], ['dark', 'Dark', 'moon']].map(([v, l, icon]) => (
            <button key={v} type="button" role="radio" aria-checked={prefs.theme === v} className={prefs.theme === v ? 'on' : ''} onClick={() => onPrefs({ theme: v })}>
              <Icon name={icon} size={15} /> {l}
            </button>
          ))}
        </div>
      </section>

      <section className="settings-section">
        <h3>Answers</h3>
        <Toggle id="pref-stream" label="Stream answers" hint="Show the answer as it is generated. Turn off to wait for the complete answer."
          checked={prefs.streaming} onChange={(v) => onPrefs({ streaming: v })} />
      </section>
    </Modal>
  )
}
