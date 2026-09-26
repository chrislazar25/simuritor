import { formatMwh, formatPct, formatUsd } from './format.ts'
import type { FleetStats } from './types.ts'

/**
 * Homes by power state (the swatches double as the map legend; the rows add up to the fleet),
 * then net revenue, promise kept and headroom.
 */
export function Counters({ fleet }: { fleet: FleetStats | null }) {
  const homes = [
    { label: 'On grid', value: fleet && fleet.homes_on_grid - fleet.homes_exporting, visual: 'grid' },
    { label: 'Exporting', value: fleet?.homes_exporting, visual: 'export' },
    { label: 'On battery', value: fleet?.homes_on_battery, visual: 'backup' },
    { label: 'Dark: ran out', value: fleet?.homes_dark, visual: 'dark' },
    { label: 'Dark: by contract', value: fleet?.homes_dark_by_contract, visual: 'dark-contract' },
  ]
  return (
    <dl className="counters">
      {homes.map(({ label, value, visual }) => (
        <div key={label}>
          <dt>
            <span className="swatch" data-visual={visual} />
            {label}
          </dt>
          <dd>{value ?? '–'}</dd>
        </div>
      ))}
      <div className="metrics-start">
        <dt>Net revenue</dt>
        <dd>
          {fleet ? formatUsd(fleet.revenue_usd) : '–'}
          {fleet && fleet.penalty_usd > 0 && <span className="sub">incl. {formatUsd(-fleet.penalty_usd)} penalties</span>}
        </dd>
      </div>
      <div>
        <dt>Promise kept</dt>
        <dd>{fleet ? (fleet.promise_kept === null ? '—' : formatPct(fleet.promise_kept)) : '–'}</dd>
      </div>
      <div>
        <dt>Headroom</dt>
        <dd>{fleet ? formatMwh(fleet.headroom_mwh) : '–'}</dd>
      </div>
    </dl>
  )
}
