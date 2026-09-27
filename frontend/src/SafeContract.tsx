import { useEffect, useRef, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceDot, ReferenceLine, XAxis, YAxis } from 'recharts'
import { formatPct, formatPower } from './format.ts'
import { scenarioQuery, type Terms } from './terms.ts'
import { cssVar } from './tokens.ts'
import type { SafeContractCurve, SafeContractResponse } from './types.ts'

// These mirror backend constants the wire doesn't carry (docs/notes.md, "To do").
const SAFE_KEPT = 0.95 // SAFE_KEPT in backend/safe_contract.py
const HOME_MAX_KW = 12 // FleetConfig.max_kw in backend/sim.py: nameplate = homes x max kW

type Result = { query: string } & ({ response: SafeContractResponse } | { error: string })

const scenario = (r: SafeContractResponse, name: SafeContractCurve['scenario']) =>
  r.scenarios.find((s) => s.scenario === name)

/**
 * The answer in one or two sentences: "Sign up to 5.4 MW (15% of this fleet); above that, Uri breaks
 * promises. In a normal winter week, up to 60% holds."
 */
function verdict(r: SafeContractResponse): string {
  const uri = scenario(r, 'uri')
  if (!uri) return 'No Uri answer came back.'
  const smallest = uri.curve[0]?.contract ?? 0
  const largest = uri.curve.at(-1)?.contract
  const normal = scenario(r, 'normal')
  const normalNote =
    normal?.safe != null ? ` In a normal winter week, up to ${formatPct(normal.safe)} holds.` : ''
  if (uri.safe === null) {
    return `Even ${formatPct(smallest)} is too much: no contract size keeps ${formatPct(SAFE_KEPT)} of its storm calls through Uri.${normalNote}`
  }
  const size = `${formatPower((uri.safe * r.params.homes * HOME_MAX_KW) / 1000)} (${formatPct(uri.safe)} of this fleet)`
  if (uri.safe === largest) return `Up to ${size}, the largest size tried, keeps at least ${formatPct(SAFE_KEPT)} of storm calls through Uri.${normalNote}`
  return `Largest size that keeps at least ${formatPct(SAFE_KEPT)} of storm calls through Uri: ${size}. Above that, promises break.${normalNote}`
}

/** Uri storm promise kept against contract size, the 95% bar, the safe point, and the normal week when it had calls. */
function SafeCurve({ response }: { response: SafeContractResponse }) {
  const pct = (f: number | null) => (f === null ? null : Math.round(f * 1000) / 10)
  const uri = scenario(response, 'uri')
  const normalKept = new Map(scenario(response, 'normal')?.curve.map((p) => [p.contract, p.kept]))
  if (!uri) return null
  const data = uri.curve.map((p) => ({
    contract: pct(p.contract),
    storm: pct(p.kept),
    normal: pct(normalKept.get(p.contract) ?? null),
  }))
  const hasNormal = data.some((p) => p.normal !== null)
  const safe = uri.curve.find((p) => p.contract === uri.safe)
  const muted = cssVar('--muted')
  const axis = { stroke: muted, fontSize: 10, tickLine: false }
  return (
    <LineChart
      width={288}
      height={128}
      data={data}
      margin={{ top: 6, right: 8, bottom: 0, left: -18 }}
      accessibilityLayer
      aria-label="Storm promise kept by contract size"
    >
      <CartesianGrid stroke={cssVar('--border')} vertical={false} />
      <XAxis dataKey="contract" type="number" domain={[0, 60]} ticks={[0, 20, 40, 60]} unit="%" {...axis} />
      <YAxis domain={[0, 100]} ticks={[0, 50, 100]} unit="%" {...axis} />
      <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />
      <ReferenceLine
        y={SAFE_KEPT * 100}
        stroke={muted}
        strokeDasharray="4 4"
        label={{ value: formatPct(SAFE_KEPT), position: 'insideTopRight', fill: muted, fontSize: 10 }}
      />
      {hasNormal && (
        <Line
          dataKey="normal"
          name="Normal week"
          stroke={muted}
          strokeDasharray="3 3"
          dot={false}
          activeDot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
      )}
      <Line
        dataKey="storm"
        name="Storm kept"
        stroke={cssVar('--accent')}
        dot={{ r: 2 }}
        activeDot={false}
        strokeWidth={1.5}
        isAnimationActive={false}
      />
      {safe && (
        // No storm calls counts as kept, so such a point sits on 100%.
        <ReferenceDot
          x={pct(safe.contract)!}
          y={pct(safe.kept) ?? 100}
          r={4}
          fill={cssVar('--state-grid')}
          stroke={cssVar('--surface')}
          label={{ value: 'safe', position: 'bottom', fill: cssVar('--state-grid'), fontSize: 10 }}
        />
      )}
    </LineChart>
  )
}

/**
 * "Find safe contract": replays every contract size under `terms` on the backend
 * (GET /api/safe-contract, a few seconds) and says how big a contract the fleet can keep.
 * An answer only shows while the terms it was asked for are still the ones on screen.
 */
export function SafeContract({ terms }: { terms: Terms }) {
  const query = scenarioQuery(terms)
  const [result, setResult] = useState<Result | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const inFlight = useRef<AbortController | null>(null)
  const answer = useRef<HTMLDivElement>(null)

  useEffect(() => () => inFlight.current?.abort(), [])

  async function find() {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setPending(query)
    try {
      const res = await fetch(`/api/safe-contract?${query}`, { signal: controller.signal })
      if (!res.ok) throw new Error(`the backend answered ${res.status}`)
      setResult({ query, response: (await res.json()) as SafeContractResponse })
    } catch (err) {
      if (controller.signal.aborted) return
      setResult({ query, error: err instanceof Error ? err.message : String(err) })
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null
        setPending(null)
      }
    }
  }

  const busy = pending === query
  const shown = result?.query === query ? result : null

  // The panel is usually too short to show the answer under the knobs: bring it into view.
  useEffect(() => {
    if (!shown) return
    const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches
    answer.current?.scrollIntoView({ block: 'nearest', behavior: smooth ? 'smooth' : 'auto' })
  }, [shown])
  return (
    <div className="safe-contract">
      <button
        type="button"
        className="find-safe"
        onClick={find}
        disabled={busy}
        aria-busy={busy}
        title="Replays every contract size from 5% to 60% under these terms, three seeds each"
      >
        {busy && <span className="spinner" aria-hidden="true" />}
        {busy ? 'Replaying Uri…' : 'Find safe contract'}
      </button>
      <div ref={answer} aria-live="polite">
        {shown && 'error' in shown && <p className="terms-error">Couldn't get an answer: {shown.error}.</p>}
        {shown && 'response' in shown && (
          <>
            <p className="verdict">{verdict(shown.response)}</p>
            <SafeCurve response={shown.response} />
          </>
        )}
      </div>
    </div>
  )
}
