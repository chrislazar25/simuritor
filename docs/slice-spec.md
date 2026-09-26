# Walking skeleton (Fri night) — spec with defaults

Goal by ~1am: press Play → the Uri week replays tick by tick, backend streams each tick over a websocket, the map and one chart update live. Ugly is fine; it must run end to end. Everything else (Jev, chaos, insight, load-based outages) plugs into this on Saturday.

## In scope tonight
1. **Data loader** — RT price `LZ_AEN` (one row per interval; the energy-weighted variant is `LZ_AEN_EW`, see `scripts/fetch_prices.py`), hourly temp (forward-fill to 15-min), EEA status table (hard-coded below).
2. **Fleet sim** — N seeded homes, each tick: household drain → apply action → update charge.
3. **Naive dispatcher** — price rules only (no Jev yet), behind a `Policy` interface so rules+Jev swaps in Saturday.
4. **Fixed outages** — a set fraction of homes lose grid power during a fixed window (below).
5. **Replay loop + websocket** — backend steps ticks at a chosen speed, pushes one JSON message per tick.
6. **Frontend** — Austin map with one dot per home, price + delivered-MW chart, play/pause/speed, headline stats.

## Out of scope tonight
Jev, confidence gate, circuit breaker, chaos injection, policy comparison, day-ahead layer, load-based shed model, deploy.

## Defaults (change if you disagree — marked ⚠ = assumption, say so in README)
| Thing | Default |
|---|---|
| Replay window | Feb 13 00:00 → Feb 20 00:00 (672 ticks). Full Feb 10–21 available. |
| Tick | one 15-min ERCOT interval; default speed 8 ticks/sec (~85 s full replay) |
| Fleet size | 500 tonight, scale to 2,000+ Saturday |
| Home location | random points inside Austin (bbox ≈ lat 30.15–30.45, lon −97.90 to −97.60), seeded |
| Battery | 60% 25 kWh (Gen2), 40% 39.2 kWh (Core); reserve floor 20% |
| Max charge/discharge power | ⚠ 10 kW per home |
| Starting charge | uniform 60–95% |
| Household mix | 70% standard · 10% medical device · 10% elderly · 10% work-from-home |
| Household drain | ⚠ kW = 0.8 + 0.12 × max(0, 65 − temp°F) (≈ 7 kW at 13°F), ±20% per-home noise |
| Outage window | ⚠ Feb 15 02:00 → Feb 18 12:00 (start matches the ~10 GW load drop 1–2am Feb 15 in ERCOT load data; end to verify) |
| Outage share | ⚠ 40% of homes, chosen at random (seeded) at window start; fixed for the window tonight |
| EEA status | Feb 15: EEA1 00:15 → EEA2 01:07 → EEA3 01:25 · Feb 19: EEA2 09:00 → EEA1 10:00 → Normal 10:35 (sourced, approximate; see `EEA_TIMELINE` in `backend/data.py`) |
| Naive policy | price ≥ $1,000 and charge > floor+10% → discharge · price ≤ $30 and charge < 90% → charge · else hold · home in outage → powers own house from battery (no export) |
| Revenue | discharged kWh × price / 1000 per tick (charging costs the same way) |
| Available MW | what the fleet could physically export this tick (homes on grid, above floor) |
| Promised MW | MW committed ahead of time — `null` tonight (no commitment source); Saturday a day-ahead plan fills it |
| Delivered MW | sum of actual discharge this tick |

## Home dot colours (map)
green = on grid, idle/charging · blue = exporting · amber = grid out, running on battery · grey/dark = grid out and battery at 0 (the "lights out" state we want to avoid)

## Wire contract (locked)
- **Source of truth:** `backend/schema.py` (fields, types, bounds, meanings). Generated from it: `schema/simuritor.schema.json`, `frontend/src/types.ts`. Examples: `fixtures/init_sample.json`, `fixtures/tick_sample.json`.
- **Backend → frontend:** `init` (static home facts, replay window) once on connect and after every reset, then one `tick` per interval with the full per-home state (not deltas). Tick homes join init homes by `id`.
- **Frontend → backend:** `play` · `pause` · `speed` · `reset` (reset = pause at tick 0 and resend `init`). Invalid messages are logged and ignored; the socket stays open.
- **Sessions:** one replay per websocket connection; tabs don't affect each other.

## Repo layout
```
backend/  app.py (FastAPI + ws) · sim.py (fleet, tick) · policy.py (Policy interface, NaivePolicy) · data.py (loaders, EEA table)
frontend/ Vite + React: Map.tsx (MapLibre + Carto) · Charts.tsx (Recharts) · Controls.tsx · useTicks.ts (ws hook)
data/     parquet files (copied from prep repo)
```

## Done means
Play → 672 ticks stream without crashing, dots change colour when outages hit Feb 15 02:00, revenue counter climbs through Feb 16–18, reset works. Commit + push.
