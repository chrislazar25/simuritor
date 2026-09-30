import { useEffect, useState } from 'react'
import { Charts } from './Charts.tsx'
import { ContractTerms, TermsSummary } from './ContractTerms.tsx'
import { Controls } from './Controls.tsx'
import { Counters } from './Counters.tsx'
import { FailoverLog, FailoverSummary } from './FailoverLog.tsx'
import { FloatingPanel } from './FloatingPanel.tsx'
import { formatClock, formatPrice } from './format.ts'
import { FleetMap } from './Map.tsx'
import { ReplayOverview } from './ReplayOverview.tsx'
import { replayQuery, type Terms } from './terms.ts'
import { RECORDED } from './recordedReplay.ts'
import { RecordedTerms } from './RecordedTerms.tsx'
import { useTicks } from './useTicks.ts'

const HIDDEN_KEY = 'simuritor.panels-hidden'
const MARGIN = 16
const BELOW_TOP_BAR = 72 // the top bar floats at 12 px and is ~48 px tall
const COUNTERS_W = 360
const COUNTERS_H = 350
const TERMS_W = 360
const TERMS_H = 420
const ATTRIBUTION_H = 40 // MapLibre's credit line, bottom-right, stays readable under the terms panel

function loadHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === 'true'
  } catch {
    return false
  }
}

/** "Hide panels" for a bare map in the Loom: the top bar stays. Toggled by the button or the H key; persisted. */
function usePanelsHidden() {
  const [hidden, setHidden] = useState(loadHidden)

  useEffect(() => {
    try {
      localStorage.setItem(HIDDEN_KEY, String(hidden))
    } catch {
      // Storage blocked: the toggle just won't survive a reload.
    }
  }, [hidden])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'h' || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return
      const target = e.target as HTMLElement
      if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      setHidden((h) => !h)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return [hidden, setHidden] as const
}

// The HUD from docs/design.md: the map fills the viewport; a fixed glass top bar and draggable glass
// panels float over it. Replay and failovers sit left; terms and fleet sit right.
export default function App() {
  // The page's query string is the replay's params, so a link reproduces the run.
  const [query, setQuery] = useState(() => location.search.slice(1))
  const { status, rejected, init, tick, history, failovers, playing, send } = useTicks(query ? `/ws?${query}` : '/ws')
  const [panelsHidden, setPanelsHidden] = usePanelsHidden()
  const finished = init !== null && tick?.i === init.n_ticks - 1
  // Keep the experiment above the live fleet readout. Compact screens use a CSS grid.
  const termsSpace = window.innerHeight - BELOW_TOP_BAR - COUNTERS_H - MARGIN - ATTRIBUTION_H

  /** Restart with `terms` (null: the backend's defaults): a new connection, unless nothing changed. */
  function replay(terms: Terms | null) {
    const next = terms ? replayQuery(terms, location.search) : ''
    window.history.replaceState(null, '', next ? `?${next}` : location.pathname)
    if (next === query) send({ type: 'reset' })
    else setQuery(next)
  }

  return (
    <div className="app">
      {/* The bar comes first so Tab reaches the controls before the map; it's fixed, so order doesn't move it. */}
      <header className="topbar">
        <span className="brand">SIMURITOR</span>
        <span className="readout clock">{tick ? formatClock(tick.t) : init ? formatClock(init.start) : '–'}</span>
        <span className="eea" data-level={tick?.eea ?? 'Normal'}>
          {tick?.eea ?? 'Normal'}
        </span>
        <span className="readout price">{tick ? formatPrice(tick.price) : '–'}</span>
        <span className="readout temp">{tick ? `${tick.temp_f.toFixed(0)}°F` : '–'}</span>
        {/* The slot is always there (hidden outside calls), so nothing shifts when a call starts or ends. */}
        <span className="call" data-active={tick?.fleet.utility_call ?? false} aria-hidden={!tick?.fleet.utility_call}>
          Utility call
        </span>
        <Controls connected={status === 'open' && init !== null} playing={playing} finished={finished} send={send} />
        <button
          type="button"
          className="hide-panels"
          aria-pressed={panelsHidden}
          title="Hide or show every panel except this bar (H)"
          onClick={() => setPanelsHidden((h) => !h)}
        >
          {panelsHidden ? 'Show panels' : 'Hide panels'}
        </button>
        <span className="readout status" data-status={status} role="status">
          {rejected
            ? 'Invalid terms'
            : status === 'open'
              ? RECORDED ? 'Recorded demo' : 'Connected'
              : status === 'connecting'
                ? 'Connecting…'
                : 'Reconnecting…'}
        </span>
      </header>
      <main className="map">
        <FleetMap init={init} tick={tick} />
      </main>
      {!panelsHidden && (
        <div className="panels">
          <FloatingPanel
            title="Replay"
            storageKey="simuritor.overview-panel"
            initial={{ w: 400, h: 224, x: MARGIN, y: BELOW_TOP_BAR }}
          >
            <ReplayOverview init={init} tick={tick} playing={playing} status={status} rejected={rejected} />
          </FloatingPanel>
          <FloatingPanel
            title="Contract terms"
            storageKey="simuritor.terms-panel-v2"
            initial={{
              w: TERMS_W,
              h: Math.min(TERMS_H, termsSpace),
              x: window.innerWidth - TERMS_W - MARGIN,
              y: BELOW_TOP_BAR,
            }}
            summary={<TermsSummary init={init} />}
          >
            {RECORDED ? <RecordedTerms init={init} rejected={rejected} onReplay={replay} /> : <ContractTerms init={init} rejected={rejected} onReplay={replay} />}
          </FloatingPanel>
          <FloatingPanel
            title="Failovers"
            storageKey="simuritor.failover-panel-v2"
            initial={{ w: 440, h: 200, x: MARGIN, y: BELOW_TOP_BAR + 240 }}
            summary={<FailoverSummary fleet={tick?.fleet ?? null} />}
          >
            <FailoverLog events={failovers} />
          </FloatingPanel>
          <FloatingPanel
            title="Fleet"
            storageKey="simuritor.counters-panel-v2"
            initial={{
              w: COUNTERS_W,
              h: COUNTERS_H,
              x: window.innerWidth - COUNTERS_W - MARGIN,
              y: window.innerHeight - COUNTERS_H - ATTRIBUTION_H,
            }}
          >
            <Counters fleet={tick?.fleet ?? null} />
          </FloatingPanel>
          <FloatingPanel title="Price · fleet MW" storageKey="simuritor.chart-panel-v2" initial={{ w: 520, h: 240 }}>
            <Charts init={init} history={history} />
          </FloatingPanel>
        </div>
      )}
    </div>
  )
}
