import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClientMessage, FailoverEvent, InitMessage, ServerMessage, TickMessage } from './types.ts'

export type ConnectionStatus = 'connecting' | 'open' | 'closed'

/** The few numbers per tick the chart needs. Keeping whole ticks would hold 672 × 500 homes. */
export type TickPoint = Pick<TickMessage, 'i' | 't' | 'price'> &
  Pick<TickMessage['fleet'], 'promised_mw' | 'delivered_mw'>

/** A failover event with the tick it arrived in; `seq` is a stable key (events carry no id). */
export type LoggedFailover = FailoverEvent & { t: string; seq: number }

/** How many failovers the log keeps. */
export const FAILOVER_LOG_SIZE = 8

/** The server closes with this when the query params are invalid; retrying can't help. */
const POLICY_VIOLATION = 1008
const RETRY_MIN_MS = 500
const RETRY_MAX_MS = 5000

function socketUrl(path: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}${path}`
}

/**
 * One replay session over a websocket: keeps the latest `init` and `tick`,
 * and reconnects with backoff when the socket closes. `path` may carry the replay's query params
 * (`/ws?contract=0.1`); a new path is a new session. If the server rejects the params it closes
 * with a reason, which lands in `rejected`, and there's no retry.
 *
 * `history` has one point per tick received since the last `init`. Points are collected
 * per message and painted in batches, so no point is lost during fast playback.
 * `failovers` is the last few failover events, newest first, kept the same way.
 *
 * `playing` mirrors the server's play state, which it never sends: play/pause
 * set it, and the server pauses itself on every `init` (connect or reset) and
 * after the last tick.
 */
export function useTicks(path = '/ws') {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  // Keyed by path, so a new path starts unrejected without a reset.
  const [rejection, setRejection] = useState<{ path: string; reason: string } | null>(null)
  const rejected = rejection?.path === path ? rejection.reason : null
  const [init, setInit] = useState<InitMessage | null>(null)
  const [tick, setTick] = useState<TickMessage | null>(null)
  const [history, setHistory] = useState<TickPoint[]>([])
  const [failovers, setFailovers] = useState<LoggedFailover[]>([])
  const [playing, setPlaying] = useState(false)
  const socket = useRef<WebSocket | null>(null)

  useEffect(() => {
    let disposed = false
    let retryMs = RETRY_MIN_MS
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let nTicks = 0
    let seq = 0
    let frame: number | undefined
    let latest: TickMessage | null = null
    let points: TickPoint[] = []
    let events: LoggedFailover[] = []

    function clearPending() {
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = undefined
      latest = null
      points = []
      events = []
    }

    // In a fast replay, consume queued messages before painting again. Every chart point
    // and recent failover is retained, but intermediate map renders can be skipped.
    function paint() {
      frame = undefined
      if (disposed || !latest) return
      const nextPoints = points
      const nextEvents = events
      setTick(latest)
      setHistory((h) => [...h, ...nextPoints])
      if (nextEvents.length > 0) setFailovers((f) => [...nextEvents, ...f].slice(0, FAILOVER_LOG_SIZE))
      if (latest.i === nTicks - 1) setPlaying(false)
      latest = null
      points = []
      events = []
    }

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
            clearPending()
            nTicks = msg.n_ticks
            setInit(msg)
            setTick(null)
            setHistory([])
            setFailovers([])
            setPlaying(false)
            break
          case 'tick':
            latest = msg
            points.push({
              i: msg.i,
              t: msg.t,
              price: msg.price,
              promised_mw: msg.fleet.promised_mw,
              delivered_mw: msg.fleet.delivered_mw,
            })
            if (msg.failovers.length > 0) {
              // Events arrive oldest first within a tick; the log is newest first.
              const logged = msg.failovers.map((e) => ({ ...e, t: msg.t, seq: seq++ })).reverse()
              events = [...logged, ...events].slice(0, FAILOVER_LOG_SIZE)
            }
            if (frame === undefined) frame = requestAnimationFrame(paint)
            break
        }
      }
      ws.onclose = (event) => {
        if (socket.current === ws) socket.current = null
        if (disposed) return
        setStatus('closed')
        setPlaying(false)
        if (event.code === POLICY_VIOLATION) {
          setRejection({ path, reason: event.reason || 'The server rejected these parameters' })
          return
        }
        retryTimer = setTimeout(connect, retryMs)
        retryMs = Math.min(retryMs * 2, RETRY_MAX_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      clearPending()
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

  return { status, rejected, init, tick, history, failovers, playing, send }
}
