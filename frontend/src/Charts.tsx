import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { formatDay } from './format.ts'
import { cssVar } from './tokens.ts'
import type { InitMessage } from './types.ts'
import type { TickPoint } from './useTicks.ts'

const TICK_MS = 15 * 60 * 1000
const TICKS_PER_DAY = 96

/**
 * Price and delivered MW over the ticks so far, on two y-axes. The x-axis spans the whole
 * replay from the start, so the lines fill left to right as it plays.
 */
export function Charts({ init, history }: { init: InitMessage | null; history: TickPoint[] }) {
  if (!init) return null
  const start = new Date(init.start).getTime()
  const midnights = Array.from({ length: Math.ceil(init.n_ticks / TICKS_PER_DAY) }, (_, d) => d * TICKS_PER_DAY)
  const text = cssVar('--text')
  const muted = cssVar('--muted')

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={history} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={cssVar('--border')} vertical={false} />
        <XAxis
          dataKey="i"
          type="number"
          domain={[0, init.n_ticks - 1]}
          ticks={midnights}
          tickFormatter={(i: number) => formatDay(new Date(start + i * TICK_MS))}
          stroke={muted}
          fontSize={11}
        />
        <YAxis yAxisId="price" stroke={muted} fontSize={11} width={48} />
        <YAxis yAxisId="mw" orientation="right" stroke={muted} fontSize={11} width={36} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          yAxisId="price"
          dataKey="price"
          name="Price $/MWh"
          stroke={text}
          dot={false}
          strokeWidth={1}
          isAnimationActive={false}
        />
        <Line
          yAxisId="mw"
          dataKey="delivered_mw"
          name="Delivered MW"
          stroke={cssVar('--state-export')}
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
