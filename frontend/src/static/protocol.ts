/** Messages between the static demo's pages and `sim.worker.ts`. */
import type { ClientMessage } from '../types.ts'

export type WorkerRequest =
  | { type: 'open'; sid: number; query: string }
  | { type: 'close'; sid: number }
  | { type: 'control'; sid: number; msg: ClientMessage }
  | { type: 'call'; id: number; fn: 'sweep_key' | 'sweep_jobs' | 'summarise' | 'aggregate'; args: unknown[] }

export type WorkerReply =
  | { type: 'loading' }
  | { type: 'ready' }
  | { type: 'fatal'; error: string }
  | { type: 'opened'; sid: number }
  | { type: 'rejected'; sid: number; reason: string }
  /** A server message (`init` or `tick`), as the JSON the websocket would carry. */
  | { type: 'server'; sid: number; data: string }
  | { type: 'result'; id: number; value?: string; error?: string }
