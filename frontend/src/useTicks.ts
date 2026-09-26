import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClientMessage, InitMessage, ServerMessage, TickMessage } from './types.ts'

export type ConnectionStatus = 'connecting' | 'open' | 'closed'

const RETRY_MIN_MS = 500
const RETRY_MAX_MS = 5000

function socketUrl(path: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}${path}`
}

/**
 * One replay session over a websocket: keeps the latest `init` and `tick`,
 * and reconnects with backoff when the socket closes.
 */
export function useTicks(path = '/ws') {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [init, setInit] = useState<InitMessage | null>(null)
  const [tick, setTick] = useState<TickMessage | null>(null)
  const socket = useRef<WebSocket | null>(null)

  useEffect(() => {
    let disposed = false
    let retryMs = RETRY_MIN_MS
    let retryTimer: ReturnType<typeof setTimeout> | undefined

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
            setInit(msg)
            setTick(null)
            break
          case 'tick':
            setTick(msg)
            break
        }
      }
      ws.onclose = () => {
        if (socket.current === ws) socket.current = null
        if (disposed) return
        setStatus('closed')
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
    return true
  }, [])

  return { status, init, tick, send }
}
