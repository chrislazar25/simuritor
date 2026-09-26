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
| EEA status | Normal → EEA3 Feb 15 01:25 → Normal Feb 19 09:00 (⚠ verify times) |
| Naive policy | price ≥ $1,000 and charge > floor+10% → discharge · price ≤ $30 and charge < 90% → charge · else hold · home in outage → powers own house from battery (no export) |
| Revenue | discharged kWh × price / 1000 per tick (charging costs the same way) |
| Promised MW | fleet exportable power at tick start (homes on grid, above floor) — Saturday this becomes the day-ahead commitment |
| Delivered MW | sum of actual discharge this tick |

## Home dot colours (map)
green = on grid, idle/charging · blue = exporting · amber = grid out, running on battery · grey/dark = grid out and battery at 0 (the "lights out" state we want to avoid)

## Tick message (backend → frontend, one per tick) — lock this first
```json
{
  "type": "tick",
  "i": 212,
  "t": "2021-02-15T05:00:00-06:00",
  "price": 9000.0,
  "eea": "EEA3",
  "temp_f": 8.1,
  "homes": [
    {"id": "h0001", "lat": 30.27, "lon": -97.74, "soc": 0.62, "grid": true,
     "action": "discharge", "kw": 10.0, "src": "rule", "conf": null}
  ],
  "fleet": {
    "promised_mw": 3.1, "delivered_mw": 2.8,
    "homes_on_grid": 300, "homes_on_battery": 190, "homes_dark": 10,
    "revenue_usd": 12450.0, "revenue_tick_usd": 630.0
  }
}
```
- `src` ∈ `rule | jev | fallback` and `conf` are null/rule tonight; they exist so Saturday needs no schema change.
- Static homes fields (`lat`, `lon`, household) can move to a one-time `init` message if payload size matters at 2,000+ homes.
- Control messages frontend → backend: `{"type":"play"}`, `{"type":"pause"}`, `{"type":"speed","ticks_per_sec":8}`, `{"type":"reset"}`.

## Repo layout
```
backend/  app.py (FastAPI + ws) · sim.py (fleet, tick) · policy.py (Policy interface, NaivePolicy) · data.py (loaders, EEA table)
frontend/ Vite + React: Map.tsx (MapLibre + Carto) · Charts.tsx (Recharts) · Controls.tsx · useTicks.ts (ws hook)
data/     parquet files (copied from prep repo)
```

## Done means
Play → 672 ticks stream without crashing, dots change colour when outages hit Feb 15 02:00, revenue counter climbs through Feb 16–18, reset works. Commit + push.
