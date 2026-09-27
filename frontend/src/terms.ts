import type { ReplayParams } from './types.ts'

type Base = {
  key: keyof ReplayParams
  label: string
  /** Tooltip: what the knob does (from `ReplayParams` in backend/schema.py). */
  hint: string
}

/** One knob in the Contract terms panel, and how to draw it. */
export type TermSpec =
  | (Base & { kind: 'choice'; options: { value: string; label: string }[] })
  /** A slider; `scale` turns the wire value into the shown one (0.3 → 30 %). */
  | (Base & { kind: 'range'; min: number; max: number; step: number; scale?: number; unit: string })
  | (Base & { kind: 'number'; min: number; max: number; step: number; unit: string })
  | (Base & { kind: 'toggle' })

/**
 * The knobs the Contract terms panel shows, in order, mirroring `ReplayParams` (backend/schema.py).
 * A new param is one line here; a knob the backend doesn't send in `init.params` is hidden, so a
 * line can land before the backend does. Params not listed (homes, headroom mode) keep whatever the
 * URL or the backend's defaults say.
 */
export const TERMS: TermSpec[] = [
  {
    key: 'policy',
    label: 'Policy',
    kind: 'choice',
    options: [
      { value: 'contract', label: 'Ours' },
      { value: 'naive', label: 'Naive' },
    ],
    hint: 'Ours keeps both contracts; naive is the price-rule baseline',
  },
  {
    key: 'contract',
    label: 'Contract',
    kind: 'range',
    min: 0,
    max: 100,
    step: 5,
    scale: 100,
    unit: '%',
    hint: 'Utility contract size, share of fleet nameplate',
  },
  {
    key: 'standard_backup_h',
    label: 'Standard backup',
    kind: 'range',
    min: 0,
    max: 24,
    step: 1,
    unit: ' h',
    hint: "Hours of backup the standard tier's reserve covers at the forecast temperature",
  },
  {
    key: 'max_calls_per_day',
    label: 'Calls per day',
    kind: 'range',
    min: 0,
    max: 10,
    step: 1,
    unit: '/day',
    hint: 'Utility calls that may start per day',
  },
  {
    key: 'skip_before_storm',
    label: 'Storm clause',
    kind: 'toggle',
    hint: 'No call while a severe cold snap is in the next 24 h forecast',
  },
  {
    key: 'emergency_uncapped',
    label: 'Emergency uncapped',
    kind: 'toggle',
    hint: 'During an EEA a call may start whatever the calls-per-day cap says',
  },
  {
    key: 'fault_rate',
    label: 'Fault rate',
    kind: 'number',
    min: 0,
    max: 1,
    step: 0.001,
    unit: '/home-h',
    hint: 'Silent device faults per home-hour',
  },
]

export type Terms = ReplayParams

/** The specs this backend knows: those whose key is in `init.params`. */
export function visibleTerms(params: Terms): TermSpec[] {
  return TERMS.filter((spec) => spec.key in params)
}

/** A knob's value as shown: "30%", "8 h", "Ours", "on". */
export function formatTerm(spec: TermSpec, value: unknown): string {
  switch (spec.kind) {
    case 'choice':
      return spec.options.find((o) => o.value === value)?.label ?? String(value)
    case 'range':
      return `${Math.round(Number(value) * (spec.scale ?? 1))}${spec.unit}`
    case 'number':
      return `${Number(value)}${spec.unit}`
    case 'toggle':
      return value ? 'on' : 'off'
  }
}

/** The active terms in one line: "Ours · 30% · 8 h · 1/day · 0.001/home-h · Storm clause". */
export function termsSummary(params: Terms): string {
  return visibleTerms(params)
    .flatMap((spec) => {
      const value = params[spec.key]
      if (spec.kind === 'toggle') return value ? [spec.label] : []
      return [formatTerm(spec, value)]
    })
    .join(' · ')
}

// Slider maths leaves float dust (0.15000000000000002); the wire never needs more than this.
const clean = (v: unknown) => (typeof v === 'number' ? String(Math.round(v * 1e6) / 1e6) : String(v))

/**
 * The /ws query for `terms`: every shown knob, on top of whatever else `base` (the page URL) says,
 * so hand-set params like `homes` survive a replay and the link reproduces the run.
 */
export function replayQuery(terms: Terms, base: string): string {
  const q = new URLSearchParams(base)
  for (const spec of visibleTerms(terms)) q.set(spec.key, clean(terms[spec.key]))
  return q.toString()
}

/** The /api/safe-contract query: every param but the contract size, which the endpoint sweeps. */
export function scenarioQuery(terms: Terms): string {
  const q = new URLSearchParams()
  for (const [key, value] of Object.entries(terms)) if (key !== 'contract') q.set(key, clean(value))
  return q.toString()
}
