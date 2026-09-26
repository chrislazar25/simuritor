import { useEffect, useState } from 'react'
import { Charts } from './Charts.tsx'
import { Controls } from './Controls.tsx'
import { Counters } from './Counters.tsx'
import { FailoverLog, FailoverSummary } from './FailoverLog.tsx'
import { FloatingPanel } from './FloatingPanel.tsx'
import { formatClock, formatPrice } from './format.ts'
import { FleetMap } from './Map.tsx'
import { useTicks } from './useTicks.ts'

const HIDDEN_KEY = 'simuritor.panels-hidden'
const MARGIN = 16
const BELOW_TOP_BAR = 72 // the top bar floats at 12 px and is ~48 px tall
const COUNTERS_W = 320 // FloatingPanel's minimum width

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
// panels float over it. Default spots: failovers top-left, counters top-right, chart bottom-left.
export default function App() {
  const { status, init, tick, history, failovers, playing, send } = useTicks()
  const [panelsHidden, setPanelsHidden] = usePanelsHidden()
  const finished = init !== null && tick?.i === init.n_ticks - 1

  return (
    <div className="app">
      <main className="map">
        <FleetMap init={init} tick={tick} />
      </main>
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
        <Controls connected={status === 'open'} playing={playing} finished={finished} send={send} />
        <button
          type="button"
          className="hide-panels"
          aria-pressed={panelsHidden}
          title="Hide or show every panel except this bar (H)"
          onClick={() => setPanelsHidden((h) => !h)}
        >
          {panelsHidden ? 'Show panels' : 'Hide panels'}
        </button>
        <span className="readout status">ws: {status}</span>
      </header>
      {!panelsHidden && (
        <>
          <FloatingPanel
            title="Failovers"
            storageKey="simuritor.failover-panel"
            initial={{ w: 460, h: 220, x: MARGIN, y: BELOW_TOP_BAR }}
            summary={<FailoverSummary fleet={tick?.fleet ?? null} />}
          >
            <FailoverLog events={failovers} />
          </FloatingPanel>
          <FloatingPanel
            title="Fleet"
            storageKey="simuritor.counters-panel"
            initial={{ w: COUNTERS_W, h: 300, x: window.innerWidth - COUNTERS_W - MARGIN, y: BELOW_TOP_BAR }}
          >
            <Counters fleet={tick?.fleet ?? null} />
          </FloatingPanel>
          <FloatingPanel title="Price · fleet MW" storageKey="simuritor.chart-panel" initial={{ w: 520, h: 300 }}>
            <Charts init={init} history={history} />
          </FloatingPanel>
        </>
      )}
    </div>
  )
}
