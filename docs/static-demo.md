# Static demo (in-browser backend) — 2026-09-29

The hosted demo runs the **unchanged `backend/` package in the browser** on [Pyodide](https://pyodide.org) (CPython compiled to WebAssembly), in a web worker. No server, no API keys, no paid hosting: it's a static site on GitHub Pages.

Unlike a recorded replay, every knob works: scenario, policy, contract size, backup hours, storm clause, call limits and faults, plus **Find qualifying contract**. Same params and seeds give the same numbers as the server (checked: default and 6 h-backup sweeps match `backend.safe_contract` natively).

## How it fits
- `scripts/static_demo/bridge.py`: the replay and safe-contract logic behind plain functions (no FastAPI, no process pool). Mirrors `backend.app.ReplaySession` and `backend.safe_contract.safe_contract`.
- `frontend/src/static/sim.worker.ts`: loads Pyodide from jsDelivr, mounts `backend/*.py`, `bridge.py` and `data/*.parquet`, and plays the server's part (paused at tick 0, steps at `ticks_per_sec`, reset rebuilds the same replay).
- `frontend/src/static/workers.ts`: `WorkerSocket` (just enough `WebSocket` for `useTicks`) and `staticSafeContract` (stands in for `GET /api/safe-contract`).
- `useTicks.ts`, `SafeContract.tsx`, `App.tsx`: pick the worker when `VITE_STATIC=1`. Without it, the app is exactly the live-server app.
- `scripts/static_demo/prepare.py`: stages the Python files and data into `frontend/public/py/` (gitignored) and precomputes the qualifying-contract sweep for common terms (defaults, storm clause, 4 h / 12 h backup, naive, sell headroom, spread by domain, emergency uncapped). Those answer instantly; other terms are swept in the browser across up to four workers (about a minute on a laptop; checked for 6 h backup: Uri 20%, normal 60%, same as the server).

## Build and deploy
```bash
cd frontend && npm run build:static          # prepare + VITE_STATIC=1 VITE_BASE=/simuritor-demo/ build
npx vite preview --port 4173                 # http://localhost:4173/simuritor-demo/
```
`frontend/dist/` is published as-is to the `chrislazar25/simuritor-demo` repo (GitHub Pages from its `main` branch, plus `.nojekyll`).

## Costs and limits
- First load downloads Pyodide + numpy/pandas/pyarrow/pydantic (~30 MB, cached by the browser afterwards); ~8 s to "Connected" on a fast connection.
- Python runs single-threaded per worker: playback tops out around 30–50 ticks/s, fine for the UI's 1–32.
- Custom-terms sweeps are 78 full replays in WebAssembly: ~1 minute on a 4+ core machine (the server takes ~12 s), longer on phones.
- Basemap tiles (OpenFreeMap) need internet.
