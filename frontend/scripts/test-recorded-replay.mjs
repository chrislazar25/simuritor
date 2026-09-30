import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { gzipSync } from 'node:zlib'
const source = fs.readFileSync(new URL('../src/recordedReplay.ts', import.meta.url), 'utf8').replace("import.meta.env.VITE_RECORDED_REPLAY === 'true'", 'true')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const init = { type: 'init', homes: [{ id: 'h0' }], n_ticks: 2 }
const tick = i => ({ type: 'tick', i, homes: [[0.5, true, 'hold', 0]] })
const bytes = gzipSync(JSON.stringify({ init, ticks: [tick(0), tick(1)] }))
const timers = new Map()
let timerId = 0
const context = { exports: {}, location: { origin: 'https://example.test' }, URL, Response, DecompressionStream, AbortController, queueMicrotask,
 fetch: async () => new Response(bytes), setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId }, clearTimeout: id => timers.delete(id) }
vm.runInNewContext(js, context)
const { RecordedReplay } = context.exports
const messages = []
const replay = new RecordedReplay('/ws?scenario=uri&contract=0.3')
const opened = new Promise(resolve => { replay.onopen = resolve })
replay.onmessage = event => messages.push(JSON.parse(event.data))
await opened
assert.equal(messages[0].type, 'init')
replay.send('{"type":"speed","ticks_per_sec":32}')
replay.send('{"type":"play"}')
assert.equal(messages[1].homes[0].id, 'h0')
assert.equal(messages[1].homes[0].soc, 0.5)
assert.equal(messages[1].homes[0].src, 'rule')
assert.equal([...timers.values()][0].ms, 31.25)
replay.send('{"type":"pause"}')
assert.equal(timers.size, 0)
replay.send('{"type":"play"}')
assert.equal(messages.at(-1).i, 1)
const count = messages.length
replay.send('{"type":"play"}')
assert.equal(messages.length, count)
replay.send('{"type":"reset"}')
assert.equal(messages.at(-1).type, 'init')
replay.send('{"type":"play"}')
assert.equal(messages.at(-1).i, 0)
replay.close()
assert.equal(timers.size, 0)
assert.equal(replay.readyState, 3)
const invalid = new RecordedReplay('/ws?scenario=uri&contract=0.42')
const closed = new Promise(resolve => { invalid.onclose = resolve })
const failure = await closed
assert.equal(failure.code, 1008)
assert.match(failure.reason, /recorded runs/)
assert.equal(invalid.readyState, 3)
console.log('Recorded replay: decode, speed, pause/resume, end, reset and cleanup passed')
