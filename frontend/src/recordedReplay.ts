import type { ClientMessage, InitMessage, TickMessage } from './types.ts'
export const RECORDED = import.meta.env.VITE_RECORDED_REPLAY === 'true'
export const RUNS = [
  { id: 'uri-30', label: 'Uri · 30% contract', scenario: 'uri', contract: 0.3 },
  { id: 'uri-10', label: 'Uri · 10% contract', scenario: 'uri', contract: 0.1 },
  { id: 'normal-30', label: 'Normal week · 30% contract', scenario: 'normal', contract: 0.3 },
]
type PackedTick = Omit<TickMessage, 'homes'> & { homes: [number, boolean, TickMessage['homes'][number]['action'], number][] }

/** Browser transport with the same controls as the live replay. Only the current tick expands. */
export class RecordedReplay {
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  private controller = new AbortController()
  private timer: ReturnType<typeof setTimeout> | undefined
  private recording: { init: InitMessage; ticks: PackedTick[] } | null = null
  private cursor = 0
  private speed = 8
  private playing = false

  constructor(path: string) {
    const query = new URL(path, location.origin).searchParams
    const run = RUNS.find(r => r.scenario === (query.get('scenario') ?? 'uri') && r.contract === Number(query.get('contract') ?? 0.3))
    queueMicrotask(() => { void this.load(run?.id) })
  }
  private async load(id: string | undefined) {
    try {
      if (!id) throw new Error('Choose one of the recorded runs below')
      const response = await fetch(`/replays/${id}.json.gz`, { signal: this.controller.signal })
      if (!response.ok || !response.body) throw new Error('Recording could not be loaded. Reload to retry')
      const stream = response.body.pipeThrough(new DecompressionStream('gzip'))
      this.recording = await new Response(stream).json()
      if (this.controller.signal.aborted) return
      this.readyState = 1
      this.onopen?.()
      this.emit(this.recording!.init)
    } catch (error) {
      if (!this.controller.signal.aborted) {
        this.readyState = 3
        this.onclose?.({ code: 1008, reason: error instanceof Error ? error.message : 'Recording unavailable' })
      }
    }
  }
  private emit(message: InitMessage | TickMessage) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
  private step = () => {
    if (!this.playing || !this.recording) return
    const packed = this.recording.ticks[this.cursor++]
    const homes = packed.homes.map(([soc, grid, action, kw], i) => ({ id: this.recording!.init.homes[i].id, soc, grid, action, kw, src: 'rule' as const, conf: null }))
    this.emit({ ...packed, homes })
    if (this.cursor < this.recording.ticks.length) this.timer = setTimeout(this.step, 1000 / this.speed)
    else this.playing = false
  }
  send(raw: string) {
    const message = JSON.parse(raw) as ClientMessage
    if (!this.recording) return
    if (message.type === 'speed') this.speed = message.ticks_per_sec
    if (message.type === 'play' && !this.playing && this.cursor < this.recording.ticks.length) {
      this.playing = true
      this.step()
    }
    if (message.type === 'pause' || message.type === 'reset') {
      this.playing = false
      clearTimeout(this.timer)
      if (message.type === 'reset') {
        this.cursor = 0
        this.emit(this.recording.init)
      }
    }
  }
  close() {
    this.controller.abort()
    clearTimeout(this.timer)
    this.playing = false
    this.recording = null
    this.readyState = 3
  }
}
