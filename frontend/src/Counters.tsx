import { formatUsd } from './format.ts'
import type { FleetStats } from './types.ts'

/** Homes by power state (swatches double as the map legend), plus cumulative revenue. */
export function Counters({ fleet }: { fleet: FleetStats | null }) {
  const rows = [
    { label: 'On grid', value: fleet?.homes_on_grid, swatch: 'var(--state-grid)' },
    { label: 'On battery', value: fleet?.homes_on_battery, swatch: 'var(--state-backup)' },
    { label: 'Dark', value: fleet?.homes_dark, swatch: 'var(--state-dark)' },
  ]
  return (
    <dl className="counters">
      {rows.map(({ label, value, swatch }) => (
        <div key={label}>
          <dt>
            <span className="swatch" style={{ background: swatch }} />
            {label}
          </dt>
          <dd>{value ?? '–'}</dd>
        </div>
      ))}
      <div>
        <dt>Revenue</dt>
        <dd>{fleet ? formatUsd(fleet.revenue_usd) : '–'}</dd>
      </div>
    </dl>
  )
}
