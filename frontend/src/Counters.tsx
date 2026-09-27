import { formatMwh, formatPct, formatUsd } from './format.ts'
import type { FleetStats } from './types.ts'

/**
 * Homes by power state (the swatches double as the map legend; the rows add up to the fleet),
 * then money (contract P&L, backup refill cost, net), promise kept and headroom.
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
      {/* Money reads like a statement: the contract's P&L, minus refilling backup, then the net. */}
      <div className="metrics-start">
        <dt>Contract P&amp;L</dt>
        <dd>
          {fleet ? formatUsd(fleet.contract_pnl_usd) : '–'}
          {fleet && fleet.penalty_usd > 0 && <span className="sub">incl. {formatUsd(-fleet.penalty_usd)} penalties</span>}
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
          {fleet && Math.abs(fleet.market_usd) >= 1 && <span className="sub">incl. {formatUsd(fleet.market_usd)} market</span>}
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
