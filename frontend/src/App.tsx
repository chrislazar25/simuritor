import { Charts } from './Charts.tsx'
import { Controls } from './Controls.tsx'
import { Counters } from './Counters.tsx'
import { FloatingPanel } from './FloatingPanel.tsx'
import { formatClock, formatPrice } from './format.ts'
import { FleetMap } from './Map.tsx'
import { useTicks } from './useTicks.ts'

// Layout from docs/design.md: top bar, map (the scene), right panel with counters, chart floating over the map.
export default function App() {
  const { status, init, tick, history, playing, send } = useTicks()
  const finished = init !== null && tick?.i === init.n_ticks - 1

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">SIMURITOR</span>
        <span className="readout">{tick ? formatClock(tick.t) : init ? formatClock(init.start) : '–'}</span>
        <span className="eea" data-level={tick?.eea ?? 'Normal'}>
          {tick?.eea ?? 'Normal'}
        </span>
        <span className="readout">{tick ? formatPrice(tick.price) : '–'}</span>
        <span className="readout">{tick ? `${tick.temp_f.toFixed(0)}°F` : '–'}</span>
        <span className="readout">
          tick {tick ? tick.i + 1 : 0}/{init?.n_ticks ?? '–'}
        </span>
        {/* Last of the left-hand readouts, so nothing shifts when a call starts or ends. */}
        {tick?.fleet.utility_call && <span className="call">Utility call</span>}
        <Controls connected={status === 'open'} playing={playing} finished={finished} send={send} />
        <span className="readout status">ws: {status}</span>
      </header>
      <main className="map">
        <FleetMap init={init} tick={tick} />
      </main>
      <aside className="panel">
        <Counters fleet={tick?.fleet ?? null} />
      </aside>
      <FloatingPanel title="Price · fleet MW" storageKey="simuritor.chart-panel" initialSize={{ w: 520, h: 300 }}>
        <Charts init={init} history={history} />
      </FloatingPanel>
    </div>
  )
}
