import { useEffect, useId, useRef, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
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

function ScenarioResult({
  curve,
  response,
  onApply,
}: {
  curve: SafeContractCurve
  response: SafeContractResponse
  onApply: (scenario: Terms['scenario'], contract: number) => void
}) {
  const point = curve.curve.find((p) => p.contract === curve.safe)
  const noCalls = curve.curve.every((p) => p.kept === null) || point?.kept === null
  return (
    <section className="scenario-result" aria-label={`${curve.scenario === 'uri' ? 'Uri' : 'Normal week'} result`}>
      <span className="result-label">{curve.scenario === 'uri' ? 'Uri · storm window' : 'Normal winter week'}</span>
      <strong className="result-value">
        {noCalls
          ? 'Not exercised'
          : point
            ? formatPower((point.contract * response.params.homes * HOME_MAX_KW) / 1000)
            : 'None qualify'}
      </strong>
      <p className="terms-note">
        {noCalls
          ? 'No calls at the selected size. Reliability is untested.'
          : point
            ? `${formatPct(point.contract)} of fleet power · ${formatPct(point.kept!)} of called intervals kept.`
            : 'No tested size meets both the delivery and critical-home criteria.'}
      </p>
      {point && !noCalls && (
        <>
          <p className="terms-note">
            Largest qualifying size tested
            {point.contract === curve.curve.at(-1)?.contract ? ' · sweep ceiling reached' : ''}.
          </p>
          <button type="button" className="apply-result" onClick={() => onApply(curve.scenario, point.contract)}>
            Apply {formatPct(point.contract)} · {curve.scenario === 'uri' ? 'Uri' : 'normal week'}
          </button>
        </>
      )}
    </section>
  )
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
    <ResponsiveContainer width="100%" height={180}>
      <LineChart
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
        {safe && safe.kept !== null && (
          <ReferenceDot
            x={pct(safe.contract)!}
            y={pct(safe.kept)!}
            r={4}
            fill={cssVar('--state-grid')}
            stroke={cssVar('--surface')}
            label={{ value: 'qualifies', position: 'bottom', fill: cssVar('--state-grid'), fontSize: 10 }}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}

/**
 * Compare tested contract sizes under `terms` in both historical scenarios.
 * An answer only shows while the terms it was asked for are still the ones on screen.
 */
export function SafeContract({ terms, onReplay }: { terms: Terms; onReplay: (terms: Terms) => void }) {
  const query = scenarioQuery(terms)
  const [result, setResult] = useState<Result | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const inFlight = useRef<AbortController | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()

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

  // Give both curves and the qualification rule room to be read together.
  useEffect(() => {
    if (shown && 'response' in shown && !dialog.current?.open) dialog.current?.showModal()
  }, [shown])
  return (
    <div className="safe-contract">
      <button
        type="button"
        className="find-safe"
        onClick={(e) => {
          if (e.currentTarget.form?.reportValidity()) void find()
        }}
        disabled={busy}
        aria-busy={busy}
        title="Compare contract sizes from 5% to 60% in both historical scenarios, three seeds each"
      >
        {busy && <span className="spinner" aria-hidden="true" />}
        {busy ? 'Evaluating both weeks…' : 'Find qualifying contract'}
      </button>
      <p className="terms-note">
        {busy
          ? 'Running 78 replays. New terms can take about 15 seconds.'
          : 'Compare Uri and a normal week · 5–60% of fleet power.'}
      </p>
      <div aria-live="polite">
        {shown && 'error' in shown && <p className="terms-error">Couldn't get an answer: {shown.error}.</p>}
        {shown && 'response' in shown && (
          <>
            <button type="button" onClick={() => dialog.current?.showModal()}>
              View comparison
            </button>
            <dialog ref={dialog} className="comparison-dialog" aria-labelledby={titleId}>
              <header className="comparison-header">
                <div>
                  <span className="eyebrow">Historical stress test · {shown.response.seeds.length} seeds</span>
                  <h2 id={titleId}>How much capacity qualifies?</h2>
                </div>
                <button type="button" onClick={() => dialog.current?.close()} autoFocus>
                  Close
                </button>
              </header>
              <p className="comparison-context">
                {shown.response.params.homes.toLocaleString()} homes · {shown.response.params.standard_backup_h} h
                standard backup ·{' '}
                {shown.response.params.policy === 'contract' ? 'contract-aware policy' : 'naive policy'}
                {shown.response.params.skip_before_storm ? ' · storm clause on' : ''}
              </p>
              <p className="terms-note">
                At least 95% of called intervals kept, with no additional critical homes running out versus no utility
                contract. Results are averages under the selected assumptions.
              </p>
              <div className="scenario-results">
                {shown.response.scenarios.map((curve) => (
                  <ScenarioResult
                    key={curve.scenario}
                    curve={curve}
                    response={shown.response}
                    onApply={(scenario, contract) => {
                      dialog.current?.close()
                      onReplay({ ...terms, scenario, contract })
                    }}
                  />
                ))}
              </div>
              <SafeCurve response={shown.response} />
              <p className="terms-note">Called intervals kept (%) vs. contract size (% of fleet power).</p>
              <details className="result-method">
                <summary>What qualifies? · {shown.response.seeds.length} seeds</summary>
                <p>
                  At least {formatPct(SAFE_KEPT)} of called 15-minute intervals must deliver at least 98% of promised
                  power, averaged over {shown.response.seeds.length} seeds. No more critical homes may run out than with
                  no utility contract.
                </p>
                <p>
                  Uri is scored on Feb 14–18, 2021; the comparison on Feb 21–27, 2022. With default terms, the
                  comparison week has just one call. No-call cases are untested, not evidence of reliable delivery.
                </p>
                <p>
                  Real prices and temperatures; simulated homes, loads and outages. The controller has perfect weather
                  foresight and modeled recovery delays. These results describe the selected assumptions, not a
                  guarantee for a real fleet.
                </p>
              </details>
            </dialog>
          </>
        )}
      </div>
    </div>
  )
}
