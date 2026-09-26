# Simuritor

Replays Winter Storm Uri (ERCOT, Feb 2021) against a simulated home-battery fleet and streams it to a live map, to stress-test fleet dispatch policies. Built for the Base Power hackathon. The product name is **Simuritor**; use it everywhere (code, UI, docs).

## Commands
Run from the repo root.
```
uv run pytest                               # all tests
uv run python -m scripts.gen_types          # regenerate schema JSON + frontend/src/types.ts
uv run python -m scripts.gen_types --check  # fail if generated files are stale
uv run scripts/fetch_prices.py              # rebuild data/ercot_rtm_spp_uri_2021-02.parquet from ERCOT
uv run python -m scripts.run_replay          # full Uri replay headless, daily summary
uv run uvicorn backend.app:app --reload --port 8000   # backend (health + /ws)
cd frontend && npm install && npm run dev             # frontend on :5173, proxies /ws to :8000
cd frontend && npm run build && npm run lint          # type-check + build, lint
```

## Hard rules
- **Python deps via uv only:** `uv add`, `uv add --dev`, `uv run`. Never pip, never create a venv by hand.
- **`backend/schema.py` is the wire contract.** Any change to it regenerates `schema/simuritor.schema.json` and `frontend/src/types.ts` and updates `fixtures/` in the same commit; `uv run pytest` (which runs `--check`) must pass. Never hand-edit generated files.
- **Wire models stay at the edge.** Sim, policy, data and chaos code keep their own state and never import the models in `backend/schema.py`; one serializer converts sim state to messages. Sharing the string vocabularies (`Action`, `Source`, `EEA`, `Household`) is fine.
- **The human commits.** Stop at a reviewable diff with a short summary; don't commit or push.
- Don't hand-edit files in `data/`; rebuild them with the scripts.

## Design
Swappable pieces, each behind a small interface the sim core depends on:
- **Policy**: decides each home's action per tick (`ContractPolicy`, docs/dispatch-design.md; `NaivePolicy` as the baseline).
- **Data source**: price, temperature and grid-event timeline per tick (Uri parquet files tonight; other crises or live data later).
- **Faults / chaos**: things that happen to homes or infrastructure (rolling outages plus a never-restored share, and silent device faults; telemetry and model failures later). Failover (`backend/failover.py`) covers homes that drop out of a call, on a timeline in seconds inside each tick.
- **Commitment source**: the MW promised to the utility (`UtilityContract`: 0 outside calls; `promised_mw` is null only with no contract).

Keep it lean: one interface per piece, one or two implementations. Add an abstraction only when a second use is in sight.

## Decisions so far
- One replay session per websocket connection; server sends `init` on connect and after reset, then one full `tick` per interval (no deltas).
- The deployed site plays a pre-recorded replay (a list of `ServerMessage`s, `init` first) in the browser; live mode runs locally.
- Prices: `LZ_AEN` is the standard load-zone price (ERCOT type `LZ`); energy-weighted rows are `LZ_AEN_EW`. See `docs/notes.md`.
- Fleet power: `available_mw` (could export now), `promised_mw` (committed ahead, nullable), `delivered_mw` (actually exported).

## Where things live
- `docs/slice-spec.md`: current build scope, defaults, repo layout.
- `docs/design.md`: look and feel, home visual states, theming seams.
- `docs/notes.md`: open questions, data findings, deferred ideas.
- `docs/pitch-points.md`, `docs/hackathon-guide.md`: the why, and how it's judged.
- `.claude/skills/`: playbooks (FastAPI, React, Vite, dashboards, testing) any agent may read.
