// Formatting for readouts. The replay's clock is Austin time, whatever the viewer's timezone.

const clockFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** "Mon Feb 15 02:00 CT" from an ISO timestamp. */
export function formatClock(iso: string): string {
  const p = Object.fromEntries(clockFormat.formatToParts(new Date(iso)).map((part) => [part.type, part.value]))
  return `${p.weekday} ${p.month} ${p.day} ${p.hour}:${p.minute} CT`
}

const dayFormat = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', month: 'numeric', day: 'numeric' })

/** "2/15": short enough that every day of the week fits on the narrow chart. */
export function formatDay(date: Date): string {
  return dayFormat.format(date)
}

const usdFormat = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

/** "-$191,145" */
export function formatUsd(usd: number): string {
  return usdFormat.format(usd)
}

/** "$9,000.00/MWh" */
export function formatPrice(usdPerMwh: number): string {
  return `${usdPerMwh.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}/MWh`
}

const pctFormat = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 })

/** "99.2%" from a 0–1 fraction. */
export function formatPct(fraction: number): string {
  return pctFormat.format(fraction)
}

/** "12.3 MWh" */
export function formatMwh(mwh: number): string {
  return `${mwh.toFixed(1)} MWh`
}

/** "Feb 15 03:15" (Austin time), for log lines. */
export function formatStamp(iso: string): string {
  const p = Object.fromEntries(clockFormat.formatToParts(new Date(iso)).map((part) => [part.type, part.value]))
  return `${p.month} ${p.day} ${p.hour}:${p.minute}`
}

/** "11 s"; "<1 s" for the near-instant covers of warned failovers. */
export function formatSeconds(s: number): string {
  return s < 1 ? '<1 s' : `${Math.round(s)} s`
}

/** "0.9 MW"; below 0.1 MW in kW ("36 kW"), so small test fleets don't read as 0.0 MW. */
export function formatPower(mw: number): string {
  return mw >= 0.1 ? `${mw.toFixed(1)} MW` : `${Math.round(mw * 1000)} kW`
}
