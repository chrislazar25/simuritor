import { formatMwh, formatPct, formatPower, formatUsd } from './format.ts'
import type { FleetStats } from './types.ts'

/**
 * Homes by power state (the swatches double as the map legend; the rows add up to the fleet),
 * with live delivery and reserve metrics; modeled cash flow can be expanded.
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
    <>
      <div className="delivery-summary">
        <div>
          <span>Delivered now</span>
          <strong>{fleet ? formatPower(fleet.delivered_mw) : '—'}</strong>
        </div>
        <div>
          <span>Promised now</span>
          <strong>{fleet?.promised_mw != null ? formatPower(fleet.promised_mw) : '—'}</strong>
        </div>
      </div>
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
          <dt title="Called intervals meeting at least 98% of the promise, over this whole replay">Intervals kept</dt>
          <dd>{fleet ? (fleet.promise_kept === null ? 'No calls yet' : formatPct(fleet.promise_kept)) : '—'}</dd>
        </div>
        <div>
          <dt>Headroom</dt>
          <dd>{fleet ? formatMwh(fleet.headroom_mwh) : '—'}</dd>
        </div>
      </dl>
      <details className="cash-flow">
        <summary>Modeled cash flow</summary>
        <p className="terms-note">Simulation accounting; excludes retail revenue and uses assumed capacity fees.</p>
        <dl className="counters">
          <div className="metrics-start">
            <dt title="Modeled contract cash flow; capacity fees and penalties are assumptions">
              Modeled contract P&amp;L
            </dt>
            <dd>
              {fleet ? formatUsd(fleet.contract_pnl_usd) : '–'}
              {fleet && fleet.penalty_usd > 0 && (
                <span className="sub">incl. {formatUsd(-fleet.penalty_usd)} penalties</span>
              )}
            </dd>
          </div>
          <div>
            <dt title="Charging homes back up to their reserve, whatever the price">Backup refill cost</dt>
            <dd>{fleet ? formatUsd(-fleet.backup_cost_usd) : '–'}</dd>
          </div>
          {/* Net also holds market trades outside the contract (≈ $0 with headroom kept); say so when they aren't. */}
          <div className="secondary">
            <dt>Net</dt>
            <dd>
              {fleet ? formatUsd(fleet.revenue_usd) : '–'}
              {fleet && Math.abs(fleet.market_usd) >= 1 && (
                <span className="sub">incl. {formatUsd(fleet.market_usd)} market</span>
              )}
            </dd>
          </div>
        </dl>
      </details>
    </>
  )
}
