import { useState } from 'react'
import type { ClientMessage } from './types.ts'

const SPEEDS = [1, 4, 8, 16, 32]
const DEFAULT_SPEED = 8 // the backend's DEFAULT_TICKS_PER_SEC

type Props = {
  connected: boolean
  playing: boolean
  finished: boolean
  send: (msg: ClientMessage) => boolean
}

/** Play / pause, speed and reset. Everything goes to the server; nothing plays locally. */
export function Controls({ connected, playing, finished, send }: Props) {
  const [speed, setSpeed] = useState(DEFAULT_SPEED)

  function play() {
    // Speed first: after a reconnect the new session starts at the server's default.
    send({ type: 'speed', ticks_per_sec: speed })
    send({ type: 'play' })
  }

  function changeSpeed(ticksPerSec: number) {
    setSpeed(ticksPerSec)
    send({ type: 'speed', ticks_per_sec: ticksPerSec })
  }

  return (
    <div className="controls">
      {playing ? (
        <button type="button" className="play" onClick={() => send({ type: 'pause' })}>
          Pause
        </button>
      ) : (
        <button type="button" className="play" onClick={play} disabled={!connected || finished}>
          Play
        </button>
      )}
      <select
        aria-label="Replay speed"
        value={speed}
        onChange={(e) => changeSpeed(Number(e.target.value))}
        disabled={!connected}
      >
        {SPEEDS.map((s) => (
          <option key={s} value={s}>
            {s} {s === 1 ? 'tick' : 'ticks'}/s
          </option>
        ))}
      </select>
      <button type="button" onClick={() => send({ type: 'reset' })} disabled={!connected}>
        Reset
      </button>
    </div>
  )
}
