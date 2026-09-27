import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDay } from './format.ts'
import { cssVar } from './tokens.ts'
import type { InitMessage } from './types.ts'
import type { TickPoint } from './useTicks.ts'

const TICK_MS = 15 * 60 * 1000
const TICKS_PER_DAY = 96
// These mirror backend constants the wire doesn't carry (docs/notes.md, "To do").
const SELL_AT_USD = 1000 // NaivePolicy.discharge_at_usd in backend/policy.py
const OUTAGE_START = '2021-02-15T02:00:00-06:00' // OUTAGE_START in backend/faults.py

/**
 * The band between delivered and promised MW where delivery fell short; zero height elsewhere, so
 * only shortfalls show. Null (no band) when no contract is configured.
 */
function shortfall(p: TickPoint): [number, number] | null {
  if (p.promised_mw === null) return null
  return [p.delivered_mw, Math.max(p.delivered_mw, p.promised_mw)]
}

/**
 * Price, and promised and delivered MW over the ticks so far, on two y-axes, with
 * shortfalls (delivered < promised) shaded red. The x-axis spans the whole replay from the
 * start, so the lines fill left to right as it plays.
 */
export function Charts({ init, history }: { init: InitMessage | null; history: TickPoint[] }) {
  if (!init) return null
  const start = new Date(init.start).getTime()
  const midnights = Array.from({ length: Math.ceil(init.n_ticks / TICKS_PER_DAY) }, (_, d) => d * TICKS_PER_DAY)
  const outageTick = (new Date(OUTAGE_START).getTime() - start) / TICK_MS
  const muted = cssVar('--muted')
  const exportColour = cssVar('--state-export')
  const marker = { fill: muted, fontSize: 10 }
  // promised_mw is null throughout when no contract is configured: leave its series off the legend.
  const hasContract = history.some((p) => p.promised_mw !== null)

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={history} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={cssVar('--border')} vertical={false} />
        <XAxis
          dataKey="i"
          type="number"
          domain={[0, init.n_ticks - 1]}
          ticks={midnights}
          minTickGap={20}
          tickFormatter={(i: number) => formatDay(new Date(start + i * TICK_MS))}
          stroke={muted}
          fontSize={11}
        />
        <YAxis yAxisId="price" stroke={muted} fontSize={11} width={48} />
        <YAxis yAxisId="mw" orientation="right" stroke={muted} fontSize={11} width={36} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <ReferenceLine
          yAxisId="price"
          y={SELL_AT_USD}
          ifOverflow="extendDomain"
          stroke={muted}
          strokeDasharray="4 4"
          label={{ ...marker, value: '$1k price reference', position: 'insideBottomRight' }}
        />
        {outageTick >= 0 && outageTick < init.n_ticks && <ReferenceLine
          yAxisId="price"
          x={outageTick}
          stroke={cssVar('--grid-off')}
          label={{ ...marker, value: 'outages', position: 'insideTopRight' }}
        />}
        {hasContract && (
          <Area
            yAxisId="mw"
            dataKey={shortfall}
            name="Shortfall"
            stroke="none"
            fill={cssVar('--grid-off')}
            fillOpacity={0.4}
            isAnimationActive={false}
          />
        )}
        <Line
          yAxisId="price"
          dataKey="price"
          name="Price $/MWh"
          stroke={cssVar('--text')}
          dot={false}
          strokeWidth={1}
          isAnimationActive={false}
        />
        {hasContract && (
          <Line
            yAxisId="mw"
            dataKey="promised_mw"
            name="Promised MW"
            stroke={cssVar('--text')}
            strokeDasharray="6 3"
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
          />
        )}
        <Line
          yAxisId="mw"
          dataKey="delivered_mw"
          name="Delivered MW"
          stroke={exportColour}
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
