import { formatPct, formatPower } from './format.ts'
import type { InitMessage, TickMessage } from './types.ts'
import type { ConnectionStatus } from './useTicks.ts'

/** Context and progress stay readable while the map and counters change. */
export function ReplayOverview({
  init,
  tick,
  playing,
  status,
  rejected,
}: {
  init: InitMessage | null
  tick: TickMessage | null
  playing: boolean
  status: ConnectionStatus
  rejected: string | null
}) {
  const complete = init !== null && tick?.i === init.n_ticks - 1
  const label = rejected
    ? 'Replay terms rejected'
    : status !== 'open' || !init
      ? 'Connecting to replay…'
      : complete
        ? 'Replay complete'
        : playing
          ? 'Replay running'
          : tick
            ? 'Replay paused'
            : 'Ready to replay'
  const fleet = tick?.fleet
  return (
    <div className="replay-overview">
      <span className="eyebrow">
        Austin · {init?.params.scenario === 'normal' ? 'February 2022' : 'February 2021'} · historical replay
      </span>
      <h1>{init?.params.scenario === 'normal' ? 'A normal winter week' : 'Winter Storm Uri'}</h1>
      <p className="overview-meta">
        {init
          ? `${init.params.homes.toLocaleString()} simulated home batteries · ${formatPower((init.params.homes * 12) / 1000)} fleet`
          : 'Connecting to the simulation…'}
      </p>
      <div className="replay-progress-label">
        <span>{label}</span>
        <span>{init ? formatPct((tick ? tick.i + 1 : 0) / init.n_ticks) : '—'}</span>
      </div>
      <progress aria-label="Replay progress" max={init?.n_ticks ?? 1} value={tick ? tick.i + 1 : 0} />
      <p className="overview-hint">
        {rejected
          ? 'Choose Back to defaults in Contract terms to start a valid replay.'
          : status !== 'open'
            ? 'The replay server is unavailable. Reconnecting automatically.'
            : complete
              ? 'Change the contract terms to compare another run.'
              : !init
                ? 'Preparing the fleet and historical scenario.'
                : !tick
                  ? 'Press Play to watch the replay. Evaluate contract terms to compare both weeks.'
                  : fleet?.utility_call
                    ? 'Utility call active. Watch delivered power against the promise.'
                    : fleet && fleet.homes_on_grid < (init?.homes.length ?? 0)
                      ? 'Neighborhood outages are drawing down home backup reserves.'
                      : 'Fleet on grid. Waiting for the next utility call.'}
      </p>
    </div>
  )
}
