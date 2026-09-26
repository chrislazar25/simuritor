import { formatSeconds, formatStamp } from './format.ts'
import type { FleetStats } from './types.ts'
import type { LoggedFailover } from './useTicks.ts'

// Shape, not just colour, tells warned from silent; the line also says which in words.
const MARKER = { warned: '▲', silent: '○' } as const

const cover = (s: number | null) => (s === null ? '—' : formatSeconds(s))

/** Cumulative failover counts and cover times, for the panel header. */
export function FailoverSummary({ fleet }: { fleet: FleetStats | null }) {
  if (!fleet) return null
  return (
    <span className="failover-summary">
      <span className="marker" data-kind="warned" title="Warned">
        {MARKER.warned}
      </span>{' '}
      {fleet.failovers_warned}{' '}
      <span className="marker" data-kind="silent" title="Silent">
        {MARKER.silent}
      </span>{' '}
      {fleet.failovers_silent}{' '}
      <span className="uncovered" title="Uncovered">
        ✕
      </span>{' '}
      {fleet.failovers_uncovered} · p50 {cover(fleet.failover_p50_s)} · max {cover(fleet.failover_max_s)}
    </span>
  )
}

/** The latest failovers, newest first: "Feb 15 03:15 · h0231 silent → covered in 11 s by 3 homes". */
export function FailoverLog({ events }: { events: LoggedFailover[] }) {
  if (events.length === 0) return <p className="failover-empty">No failovers yet</p>
  return (
    <ol className="failover-log">
      {events.map((e) => {
        const outcome =
          e.cover_s === null
            ? 'not covered'
            : `covered in ${formatSeconds(e.cover_s)} by ${e.covered_by} home${e.covered_by === 1 ? '' : 's'}`
        const line = `${formatStamp(e.t)} · ${e.home_id} ${e.kind} → ${outcome}`
        return (
          <li key={e.seq} title={line}>
            <span className="marker" data-kind={e.kind}>
              {MARKER[e.kind]}
            </span>{' '}
            {formatStamp(e.t)} · {e.home_id} {e.kind} →{' '}
            <span className={e.cover_s === null ? 'uncovered' : undefined}>{outcome}</span>
          </li>
        )
      })}
    </ol>
  )
}
