/**
 * The static demo's stand-ins for the server: `WorkerSocket` for `/ws` and `staticSafeContract`
 * for `GET /api/safe-contract`, both backed by `sim.worker.ts` (the Python backend on Pyodide).
 */
import type { ClientMessage, SafeContractResponse } from '../types.ts'
import type { WorkerReply, WorkerRequest } from './protocol.ts'

/** True in the GitHub Pages build (`VITE_STATIC=1`), where there's no server. */
export const STATIC = import.meta.env.VITE_STATIC === '1'

function spawn(): Worker {
  return new Worker(new URL('./sim.worker.ts', import.meta.url), { type: 'module' })
}

/** One worker, its RPC calls and its replay sessions. */
class SimWorker {
  readonly worker = spawn()
  private nextId = 0
  private calls = new Map<number, { resolve: (v: string) => void; reject: (e: Error) => void }>()
  readonly listeners = new Set<(msg: WorkerReply) => void>()
  fatal: string | null = null

  constructor() {
    this.worker.onmessage = (event: MessageEvent<WorkerReply>) => {
      const msg = event.data
      if (msg.type === 'fatal') this.fatal = msg.error
      if (msg.type === 'result') {
        const call = this.calls.get(msg.id)
        this.calls.delete(msg.id)
        if (msg.error !== undefined) call?.reject(new Error(msg.error))
        else call?.resolve(msg.value ?? '')
        return
      }
      for (const listener of this.listeners) listener(msg)
      if (msg.type === 'fatal') for (const call of this.calls.values()) call.reject(new Error(msg.error))
    }
  }

  send(msg: WorkerRequest) {
    this.worker.postMessage(msg)
  }

  call(fn: Extract<WorkerRequest, { type: 'call' }>['fn'], ...args: unknown[]): Promise<string> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.calls.set(id, { resolve, reject })
      this.send({ type: 'call', id, fn, args })
    })
  }
}

let main: SimWorker | null = null
/** The worker that plays the replay; also answers quick calls. */
function mainWorker(): SimWorker {
  main ??= new SimWorker()
  return main
}

let nextSid = 0

/** Just enough of `WebSocket` for `useTicks`: one replay session in the main worker. */
export class WorkerSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3
  readyState = WorkerSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  private readonly sid = nextSid++
  private readonly sim = mainWorker()
  private readonly listener = (msg: WorkerReply) => this.receive(msg)

  constructor(path: string) {
    const query = path.includes('?') ? path.slice(path.indexOf('?') + 1) : ''
    this.sim.listeners.add(this.listener)
    if (this.sim.fatal !== null) {
      queueMicrotask(() => this.finish(1011, this.sim.fatal ?? ''))
      return
    }
    this.sim.send({ type: 'open', sid: this.sid, query })
  }

  private receive(msg: WorkerReply) {
    if (msg.type === 'fatal') return this.finish(1011, msg.error)
    if (!('sid' in msg) || msg.sid !== this.sid) return
    switch (msg.type) {
      case 'opened':
        this.readyState = WorkerSocket.OPEN
        this.onopen?.()
        break
      case 'rejected':
        this.finish(1008, msg.reason)
        break
      case 'server':
        this.onmessage?.(new MessageEvent('message', { data: msg.data }))
        break
    }
  }

  private finish(code: number, reason: string) {
    if (this.readyState === WorkerSocket.CLOSED) return
    this.readyState = WorkerSocket.CLOSED
    this.sim.listeners.delete(this.listener)
    if (code !== 1000) console.error(`simulator: ${reason}`)
    this.onclose?.({ code, reason })
  }

  send(raw: string) {
    if (this.readyState !== WorkerSocket.OPEN) return
    this.sim.send({ type: 'control', sid: this.sid, msg: JSON.parse(raw) as ClientMessage })
  }

  close() {
    this.sim.send({ type: 'close', sid: this.sid })
    this.readyState = WorkerSocket.CLOSED
    this.sim.listeners.delete(this.listener)
  }
}

/** `/api/safe-contract` answers computed at build time (`scripts/static_demo/prepare.py`). */
let presets: Promise<Record<string, SafeContractResponse>> | null = null

let pool: SimWorker[] = []
/** Sweep workers, beside the main one, so the replay keeps playing during a sweep. */
function sweepPool(): SimWorker[] {
  if (pool.length === 0) {
    const n = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1))
    pool = Array.from({ length: n }, () => new SimWorker())
  }
  return pool
}

/**
 * `GET /api/safe-contract?${query}`: a precomputed answer when there is one, else every replay
 * of the sweep, in the browser, spread over a few workers (a minute or more).
 */
export async function staticSafeContract(query: string, signal: AbortSignal): Promise<SafeContractResponse> {
  presets ??= fetch(`${import.meta.env.BASE_URL}py/safe-contract.json`).then((r) => r.json())
  const sim = mainWorker()
  const [answers, key] = await Promise.all([presets, sim.call('sweep_key', query)])
  if (answers[key]) return answers[key]

  const jobs = JSON.parse(await sim.call('sweep_jobs')) as [string, number | null, number][]
  const workers = sweepPool()
  const summaries: string[] = new Array(jobs.length)
  let next = 0
  await Promise.all(
    workers.map(async (w) => {
      while (next < jobs.length) {
        if (signal.aborted) throw new DOMException('aborted', 'AbortError')
        const i = next++
        summaries[i] = await w.call('summarise', query, JSON.stringify(jobs[i]))
      }
    }),
  )
  const response = await sim.call('aggregate', query, `[${summaries.join(',')}]`)
  return JSON.parse(response) as SafeContractResponse
}
