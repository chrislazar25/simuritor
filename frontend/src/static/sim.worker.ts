/// <reference lib="webworker" />
/**
 * The static demo's backend: the unchanged Python `backend/` package, running in this worker
 * on Pyodide, behind `scripts/static_demo/bridge.py`. It plays the part of the server's
 * `ReplaySession` (starts paused, steps at `ticks_per_sec`, pauses after the last tick, reset
 * rebuilds the same replay) and answers the safe-contract sweep's jobs.
 */
import type { WorkerReply, WorkerRequest } from './protocol.ts'

const PYODIDE_VERSION = '314.0.7'
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
const DEFAULT_TICKS_PER_SEC = 8
const PY_BASE = new URL(`${import.meta.env.BASE_URL}py/`, self.location.origin).href

type PyProxy = { [name: string]: any; destroy(): void } // eslint-disable-line @typescript-eslint/no-explicit-any
type Pyodide = {
  loadPackage(names: string[], options?: { messageCallback?: (msg: string) => void }): Promise<unknown>
  runPython(code: string): unknown
  pyimport(name: string): PyProxy
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: Uint8Array): void }
}

async function boot(): Promise<PyProxy> {
  const { loadPyodide } = (await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)) as {
    loadPyodide(options: { indexURL: string }): Promise<Pyodide>
  }
  const [py, files] = await Promise.all([
    loadPyodide({ indexURL: PYODIDE_URL }),
    fetch(`${PY_BASE}files.json`).then((r) => r.json() as Promise<string[]>),
  ])
  const [contents] = await Promise.all([
    Promise.all(files.map((f) => fetch(`${PY_BASE}${f}`).then((r) => r.arrayBuffer()))),
    py.loadPackage(['numpy', 'pandas', 'pyarrow', 'pydantic', 'tzdata'], { messageCallback: () => {} }),
  ])
  files.forEach((f, i) => {
    py.FS.mkdirTree(`/app/${f.split('/').slice(0, -1).join('/')}`)
    py.FS.writeFile(`/app/${f}`, new Uint8Array(contents[i]))
  })
  py.runPython("import sys; sys.path.insert(0, '/app')")
  return py.pyimport('bridge')
}

const bridge = boot()

function post(msg: WorkerReply) {
  self.postMessage(msg)
}

/** The one replay this worker plays, if any. */
let session: {
  sid: number
  replay: PyProxy
  playing: boolean
  ticksPerSec: number
  timer?: ReturnType<typeof setTimeout>
} | null = null

function stop() {
  if (!session) return
  clearTimeout(session.timer)
  session.replay.destroy()
  session = null
}

function schedule(delayMs: number) {
  const s = session
  if (!s || !s.playing) return
  clearTimeout(s.timer)
  s.timer = setTimeout(() => {
    if (session !== s || !s.playing) return
    const due = performance.now() + 1000 / s.ticksPerSec
    post({ type: 'server', sid: s.sid, data: s.replay.step() as string })
    if (s.replay.done()) s.playing = false
    // Wait only what's left of the interval, so stepping doesn't slow the rate.
    else schedule(Math.max(0, due - performance.now()))
  }, delayMs)
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const msg = event.data
  let py: PyProxy
  try {
    py = await bridge
  } catch (err) {
    post({ type: 'fatal', error: String(err) })
    return
  }
  try {
    switch (msg.type) {
      case 'open': {
        stop()
        const opened = py.open_replay(msg.query)
        const reject = opened.get('reject') as string | undefined
        if (reject !== undefined) {
          opened.destroy()
          post({ type: 'rejected', sid: msg.sid, reason: reject })
          return
        }
        session = { sid: msg.sid, replay: opened.get('replay'), playing: false, ticksPerSec: DEFAULT_TICKS_PER_SEC }
        opened.destroy()
        post({ type: 'opened', sid: msg.sid })
        post({ type: 'server', sid: msg.sid, data: session.replay.init() as string })
        return
      }
      case 'close':
        if (session?.sid === msg.sid) stop()
        return
      case 'control': {
        const s = session
        if (s?.sid !== msg.sid) return
        const c = msg.msg
        if (c.type === 'play') {
          s.playing = !s.replay.done()
          schedule(0)
        } else if (c.type === 'pause') {
          s.playing = false
          clearTimeout(s.timer)
        } else if (c.type === 'speed') {
          if (c.ticks_per_sec > 0 && c.ticks_per_sec <= 32) s.ticksPerSec = c.ticks_per_sec
          schedule(1000 / s.ticksPerSec)
        } else if (c.type === 'reset') {
          s.playing = false
          clearTimeout(s.timer)
          post({ type: 'server', sid: s.sid, data: s.replay.reset() as string })
        }
        return
      }
      case 'call': {
        const fn = py[msg.fn] as (...args: unknown[]) => unknown
        post({ type: 'result', id: msg.id, value: fn(...msg.args) as string })
        return
      }
    }
  } catch (err) {
    if (msg.type === 'call') post({ type: 'result', id: msg.id, error: String(err) })
    else post({ type: 'fatal', error: String(err) })
  }
}

post({ type: 'loading' })
bridge.then(
  () => post({ type: 'ready' }),
  (err: unknown) => post({ type: 'fatal', error: String(err) }),
)
