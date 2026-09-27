import { useState } from 'react'
import { SafeContract } from './SafeContract.tsx'
import { formatTerm, type TermSpec, type Terms, termsSummary, visibleTerms } from './terms.ts'
import type { InitMessage } from './types.ts'

/** A number box that lets you type through in-between states ("0.0"); only valid numbers go up. */
function NumberField({
  spec,
  value,
  onChange,
}: {
  spec: Extract<TermSpec, { kind: 'number' }>
  value: number
  onChange: (v: number) => void
}) {
  const [text, setText] = useState(String(value))
  // Follow a value set from outside (a new init, Undo); values we sent ourselves are already `seen`.
  const [seen, setSeen] = useState(value)
  if (value !== seen) {
    setSeen(value)
    setText(String(value))
  }
  return (
    <span className="term-control">
      <input
        type="number"
        inputMode="decimal"
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={text}
        onInvalid={(e) => {
          // Native validation can target an input inside the collapsed advanced section.
          const details = e.currentTarget.closest('details')
          if (details) details.open = true
        }}
        onChange={(e) => {
          setText(e.target.value)
          const n = e.target.valueAsNumber
          if (Number.isFinite(n) && n >= spec.min && n <= spec.max) {
            setSeen(n)
            onChange(n)
          }
        }}
      />
      <span className="term-unit">{spec.unit}</span>
    </span>
  )
}

/** One knob, drawn as its spec says. `was` is the running value when the draft differs from it. */
function Term({
  spec,
  value,
  was,
  onChange,
}: {
  spec: TermSpec
  value: unknown
  was: string | null
  onChange: (v: unknown) => void
}) {
  const label = (
    <span className="term-label" title={spec.hint}>
      {spec.label}
      {was !== null && (
        <span className="term-changed" title={`Running: ${was}`} aria-label={`changed, running ${was}`} />
      )}
    </span>
  )
  switch (spec.kind) {
    case 'choice':
      return (
        <div className="term">
          {label}
          <div className="segmented" role="group" aria-label={spec.label}>
            {spec.options.map((o) => (
              <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
      )
    case 'range': {
      const scale = spec.scale ?? 1
      return (
        <label className="term">
          {label}
          <span className="term-control">
            <input
              type="range"
              min={spec.min}
              max={spec.max}
              step={spec.step}
              value={Math.round(Number(value) * scale)}
              onChange={(e) => onChange(Number(e.target.value) / scale)}
            />
            <output className="term-value">{formatTerm(spec, value)}</output>
          </span>
        </label>
      )
    }
    case 'number':
      return (
        <label className="term">
          {label}
          <NumberField spec={spec} value={Number(value)} onChange={onChange} />
        </label>
      )
    case 'toggle':
      return (
        <label className="term">
          {label}
          <input
            type="checkbox"
            className="switch"
            role="switch"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
        </label>
      )
  }
}

/** The active terms from `init`, for the panel header. */
export function TermsSummary({ init }: { init: InitMessage | null }) {
  if (!init) return null
  const summary = termsSummary(init.params)
  return (
    <span className="panel-summary" title={summary}>
      {summary}
    </span>
  )
}

/**
 * The replay's knobs, drafted here and applied by Replay (a new /ws connection with them as query
 * params). Starts from, and resets to, the terms the running replay reports in `init`.
 * `onReplay(null)` goes back to the backend's defaults.
 */
export function ContractTerms({
  init,
  rejected,
  onReplay,
}: {
  init: InitMessage | null
  rejected: string | null
  onReplay: (terms: Terms | null) => void
}) {
  const [active, setActive] = useState<Terms | null>(init?.params ?? null)
  const [draft, setDraft] = useState<Terms | null>(init?.params ?? null)
  // A new init with different terms (a replay, or a hand-edited URL) resets the draft; a plain
  // reset resends the same terms and keeps whatever you were drafting.
  if (init && JSON.stringify(init.params) !== JSON.stringify(active)) {
    setActive(init.params)
    setDraft(init.params)
  }

  if (rejected) {
    return (
      <div className="terms">
        <p className="terms-error">The backend refused these terms: {rejected}.</p>
        <button type="button" onClick={() => onReplay(null)}>
          Back to defaults
        </button>
      </div>
    )
  }
  if (!draft || !active) return <p className="failover-empty">Waiting for the backend…</p>

  const specs = visibleTerms(draft)
  const changed = specs.some((s) => draft[s.key] !== active[s.key])
  const primary = ['scenario', 'policy', 'contract', 'standard_backup_h', 'skip_before_storm']
  const field = (spec: TermSpec) => (
    <Term
      key={spec.key}
      spec={spec}
      value={draft[spec.key]}
      was={draft[spec.key] === active[spec.key] ? null : formatTerm(spec, active[spec.key])}
      onChange={(v) => setDraft({ ...draft, [spec.key]: v })}
    />
  )
  return (
    <form
      className="terms"
      onSubmit={(e) => {
        e.preventDefault()
        onReplay(draft)
      }}
    >
      <p className="panel-intro">How much can the fleet promise while protecting home backup?</p>
      {specs.filter((spec) => primary.includes(spec.key)).map(field)}
      <details className="advanced-terms">
        <summary>Call limits & device faults</summary>
        {specs.filter((spec) => !primary.includes(spec.key)).map(field)}
      </details>
      <div className="terms-actions">
        <button type="submit" className="replay" data-primary={changed} title="Restart the replay with these terms">
          {changed ? 'Apply & reset' : 'Reset replay'}
        </button>
        {changed && (
          <button type="button" onClick={() => setDraft(active)}>
            Undo changes
          </button>
        )}
      </div>
      {changed && <p className="terms-note">Draft terms · apply to update the map, or evaluate them below.</p>}
      <SafeContract terms={draft} onReplay={onReplay} />
    </form>
  )
}
