import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClientMessage, InitMessage, ServerMessage, TickMessage } from './types.ts'

export type ConnectionStatus = 'connecting' | 'open' | 'closed'

/** The few numbers per tick the chart needs. Keeping whole ticks would hold 672 × 500 homes. */
export type TickPoint = Pick<TickMessage, 'i' | 't' | 'price'> & Pick<TickMessage['fleet'], 'promised_mw' | 'delivered_mw'>

const RETRY_MIN_MS = 500
const RETRY_MAX_MS = 5000

function socketUrl(path: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}${path}`
}

/**
 * One replay session over a websocket: keeps the latest `init` and `tick`,
 * and reconnects with backoff when the socket closes.
 *
 * `history` has one point per tick received since the last `init`. It's appended
 * per message, not per render, so no tick is lost when React batches fast ticks.
 *
 * `playing` mirrors the server's play state, which it never sends: play/pause
 * set it, and the server pauses itself on every `init` (connect or reset) and
 * after the last tick.
 */
export function useTicks(path = '/ws') {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [init, setInit] = useState<InitMessage | null>(null)
  const [tick, setTick] = useState<TickMessage | null>(null)
  const [history, setHistory] = useState<TickPoint[]>([])
  const [playing, setPlaying] = useState(false)
  const socket = useRef<WebSocket | null>(null)

  useEffect(() => {
    let disposed = false
    let retryMs = RETRY_MIN_MS
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let nTicks = 0

    function connect() {
      setStatus('connecting')
      const ws = new WebSocket(socketUrl(path))
      socket.current = ws

      ws.onopen = () => {
        retryMs = RETRY_MIN_MS
        setStatus('open')
      }
      ws.onmessage = (event: MessageEvent<string>) => {
        if (disposed) return
        const msg = JSON.parse(event.data) as ServerMessage
        switch (msg.type) {
          case 'init':
            // A new init starts a new replay (connect or reset); the old tick no longer applies.
            nTicks = msg.n_ticks
            setInit(msg)
            setTick(null)
            setHistory([])
            setPlaying(false)
            break
          case 'tick':
            setTick(msg)
            setHistory((h) => [
              ...h,
              {
                i: msg.i,
                t: msg.t,
                price: msg.price,
                promised_mw: msg.fleet.promised_mw,
                delivered_mw: msg.fleet.delivered_mw,
              },
            ])
            if (msg.i === nTicks - 1) setPlaying(false)
            break
        }
      }
      ws.onclose = () => {
        if (socket.current === ws) socket.current = null
        if (disposed) return
        setStatus('closed')
        setPlaying(false)
        retryTimer = setTimeout(connect, retryMs)
        retryMs = Math.min(retryMs * 2, RETRY_MAX_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(retryTimer)
      socket.current?.close()
    }
  }, [path])

  /** Send a control message. Returns false (and drops it) if the socket isn't open. */
  const send = useCallback((msg: ClientMessage): boolean => {
    const ws = socket.current
    if (ws?.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify(msg))
    if (msg.type === 'play') setPlaying(true)
    if (msg.type === 'pause' || msg.type === 'reset') setPlaying(false)
    return true
  }, [])

  return { status, init, tick, history, playing, send }
}
