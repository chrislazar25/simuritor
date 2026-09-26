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

const usdFormat = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

/** "-$191,145" */
export function formatUsd(usd: number): string {
  return usdFormat.format(usd)
}

/** "$9,000.00/MWh" */
export function formatPrice(usdPerMwh: number): string {
  return `${usdPerMwh.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}/MWh`
}
