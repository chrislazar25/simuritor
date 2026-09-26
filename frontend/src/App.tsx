import { useTicks } from './useTicks.ts'

// Empty layout from docs/design.md: top bar, map (the scene), right panel with counters and chart slots.
export default function App() {
  const { status, tick } = useTicks()

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">SIMURITOR</span>
        <span className="readout">ws: {status}</span>
        <span className="readout">i: {tick ? tick.i : '-'}</span>
        <span className="readout">t: {tick ? tick.t : '-'}</span>
        <span className="readout">price: {tick ? `$${tick.price.toFixed(2)}/MWh` : '-'}</span>
      </header>
      <main className="map slot">map</main>
      <aside className="panel">
        <section className="slot">counters</section>
        <section className="slot">chart</section>
      </aside>
    </div>
  )
}
