# Notes: open questions and deferred ideas

## Ask at Base office hours
- Household mix (standard / medical / elderly / wfh): are these the categories that matter to Base, or are there others?
- Which ERCOT load zone do Base's homes sit in? We use `LZ_AEN`, but Austin Energy is municipal (not open to retail choice), so Base's Austin-area members may be in Oncor/PEC territory and a different zone.

## Data findings
- RT prices: gridstatus 0.36 `get_rtm_spp(year)` loses `Settlement Point Type`, so each load zone's standard (LZ) and energy-weighted (LZEW) prices both come out as e.g. `LZ_AEN`, in random order. Gap: median $0.01, max $17.10 (Feb 15 02:15). Fixed by `scripts/fetch_prices.py` reading ERCOT directly; we use `LZ`. Optional: report upstream to gridstatus. Mention in README provenance.
- EEA timeline: the original spec had "Normal Feb 19 09:00"; ERCOT actually stepped down EEA3 → EEA2 (09:00) → EEA1 (10:00) → Normal (10:35). Sourced timeline in `EEA_TIMELINE` (`backend/data.py`). Mention in README provenance.
- Replay window is Feb 10 00:00 → Feb 20 00:00 (960 ticks). Feb 10 is calm (≤ $142, 38–52°F), but the "pre-storm" days aren't all normal: Feb 11 has 16 intervals ≥ $1,000 (max $4,086) and Feb 12 has 8 (max $2,020), so a $1,000 trigger already calls the contract then (15 called ticks, all kept at every size tried). Keep that in mind when the insight experiment compares pre-storm vs storm.
- Naive policy on real Uri prices, market only (`uv run python -m scripts.run_replay --policy naive --no-contract`): it fills up at ≤ $30 on Feb 10 and sells down to the floor on the first spike on Feb 11 (~$18.3k). LZ_AEN is then ≥ $1,000 almost continuously from Feb 13 00:15 to Feb 18 (every zone and hub agrees) and never ≤ $30 until Feb 19, so it can't recharge cheaply. With rolling outages and the recovery rule (below floor on grid → charge whatever the price), homes coming back from each rotation refill to the floor at crisis prices, so the replay ends at about −$178k. Never-restored homes (except tier `none`, which skips backup) are dark by noon Feb 15; rotating homes go dark near the end of each 4 h cut because they only refill to 20%. Dark home-hours (ran out): 6,304. This is the pitch's "what a naive policy would have lost or put at risk": it sold the reserve for ~$18k four days early, then bought it back for ~10× that. Pinned by `test_naive_baseline_sells_the_reserve_then_buys_it_back_at_crisis_prices`. Quirk: at 12 kW one recovery charge (3 kWh) can overshoot floor + 10% on a 25 kWh battery, so the home resells a sliver the next tick (~$160 all week).
- ContractPolicy, seed 0, Feb 10–20, with the sourced call rules (≤ 1 call/day, 06:00–22:00) and call-ready recharge (`uv run python -m scripts.run_replay --contract-size F [--emergency-uncapped]`):

  | Contract | Calls | Called ticks | Kept | Penalties | Dark home-h | Net revenue |
  |---|---|---|---|---|---|---|
  | 10% (0.6 MW) | default | 47 | 89.4% | $3,639 | 3,284 | −$210,748 |
  | 10% | emergency uncapped | 143 | 90.2% | $9,261 | 3,284 | −$218,716 |
  | 30% (1.8 MW) | default | 47 | 76.6% | $18,159 | 3,214 | −$229,909 |
  | 30% | emergency uncapped | 143 | 80.4% | $35,570 | 3,214 | −$251,300 |
  | 60% (3.6 MW) | default | 47 | 46.8% | $110,871 | 3,160 | −$349,224 |
  | 60% | emergency uncapped | 143 | 27.3% | $381,757 | 3,160 | −$623,552 |

  For reference: no contract, −$204,043 and 3,317 dark home-hours. 30% with `--skip-before-storm`: 23 called ticks, all kept, $0 penalties, −$214,874. Naive under the old rules (60%, no daily cap) kept 1.5%.
  - The daily cap and call-ready recharge are what changed things. Before them, 10% kept 12% of 275 called ticks; now it keeps ~90%. No size reaches the 99% "safe" bar in the storm yet.
  - Emergency-uncapped triples the called ticks. At 10–30% it barely hurts (still ~80–90% kept); at 60% it breaks (27% kept, penalties 3.4×). That's where the stress case bites.
  - Most of the loss is the homeowner contract, not the utility one: with no contract at all the fleet still ends at −$204k, from recovering reserves at ~$9,000/MWh as the forecast gets colder. The contract's own cost at 10% is ~$7k.
  - Dark home-hours now fall slightly as the contract grows (3,284 → 3,160): call-ready recharge keeps more energy in batteries that backup then uses.
- Rolling outages (⚠ assumption): ERCOT and the utilities intended short rotating outages, but many circuits stayed out for days (critical-load circuits exempted, the sheer volume of load shed, ice damage). `RollingOutage` models both: 10% of homes never restored for the whole window, the rest cycling 4 h off / 6 h on (46% of the fleet out at once). The durations and shares are our assumptions, not sourced; say so in the README.
- Household drain (⚠ assumption): lowered from ~7 kW to ~2.5 kW at 13 °F so a full average battery lasts ~12 h on backup (homes shed load on backup; reasoning in `FleetConfig`). No single value makes both battery sizes last 10–14 h (25 kWh needs ≤ 2.5 kW, 39.2 kWh needs ≥ 2.8 kW).

## To do when we reach that step
- Recording for the deployed site: a tick is ~48 KiB of JSON at 500 homes (SoC/kW/MW sent unrounded so fleet stats add up exactly), so 960 ticks ≈ 46 MB. Round SoC/kW in the recording (and keep counts consistent) or compress/delta-encode it.
- Frontend visual pass: load the fonts named in `docs/design.md` (Inter Tight, JetBrains Mono); tonight the page falls back to system fonts.
- Map visual pass: the basemap is the stock OpenFreeMap "liberty" style, hard-coded in `Map.tsx`; the design wants a muted style owned by the theme. The dot colours are read from the CSS tokens once when the map loads, so a theme switch would need to re-apply the circle paint.
- Chart markers: the $1,000 sell threshold and the Feb 15 02:00 outage start are copied into `frontend/src/Charts.tsx` from `backend/policy.py` and `backend/faults.py`, because the wire doesn't carry them. When policies or outages become swappable, send them in `init` (a schema change) and drop the copies.
- Failover wiring: `failovers_*`, `failover_p50_s`/`max_s` and `TickMessage.failovers` are still placeholders in `backend/serialize.py`. `failovers_*` counts and p50/max are cumulative over the replay; per-tick detail is the `failovers` event list. `promise_kept` is a 0–1 fraction (not ×100).
- Forecast: `forecast_min_f` (`backend/sim.py`) is perfect foresight (the actual temperatures). The forecast error model replaces that one function.
- ContractPolicy plans the next call's share pro rata to room above the reserve among on-grid homes, so shares move as homes lose or regain grid. Call-ready recharge is skipped during a call (only the reserve is recovered), because `delivered_mw` counts exports only and charging would otherwise inflate promise kept.
- `UtilityContract` counts calls per Central-time day, not "one per day on average" (GVEC's wording), and doesn't track Austin Energy's 40 events a year: irrelevant for a 10-day replay, but it matters for a season-long one. The "EEA" trigger option in dispatch-design.md isn't implemented; calls trigger on price only.
- `headroom_mwh` is energy above the contract reserve, fleet total (per the build brief, docstring updated to match). It includes tier `none` homes' energy below the 20% export floor, which can't be exported (~0.3 MWh through the storm), and during a call it includes what the rest of the call will draw.
- `delivered_mw` (and so promise kept and the penalty) counts exports only. Homes recharging to their reserve during a call aren't netted against it.
- HUD: playback (play/pause, speed, reset) lives in the top bar for now; design.md's bottom timeline with a scrubber waits on `seek`. The top bar dropped the "tick N/960" readout to fit at 1440 px; temperature stays. A panel's expanded state isn't persisted (a reload comes back docked), which is deliberate. Saved panel positions from before the HUD pass may overlap the new top bar; clear `simuritor.*` in localStorage to get the defaults.
- Scene lighting: `suncalc` vs ~30 lines of our own sun math; add a "hold light level" toggle if the day/night cycle distracts in the Loom recording.

## Deferred (do if time allows)
- Frontend bundle: MapLibre and Recharts make the main JS chunk ~1.6 MB (450 kB gzipped) plus a ~510 kB worker (the two share code Vite bundles twice), and `npm run build` warns about chunk size. Lazy-load the map or split chunks only if first load feels slow on the deployed site.
- Cache the parquet reads in `UriParquetSource` (currently read once per `frames()` call, i.e. per websocket session). Only if it ever shows up as slow. Building a sim takes ~15 ms and runs on the event loop at connect and reset; move it to a thread (`asyncio.to_thread`) if many sessions ever run at once.
- Serializer speed: step + serialize + JSON is ~1.9 ms/tick at 500 homes (mostly Pydantic building 500 `HomeState`s). Fine at 64 ticks/s; at 2,000+ homes consider `model_construct` or serializing straight from arrays.
- Physics invariants (e.g. `discharge` ⇒ grid up, `backup` ⇒ grid down, `charge` ⇒ grid up). Define once and reuse for sim tests and optionally the wire models, rather than duplicating.
- TS generator deps: `gen_types` runs `json-schema-to-typescript` via `npx` (tool pinned, its deps not). If `--check` ever reports `types.ts` stale with only formatting diffs (a prettier release), make it a pinned devDependency in `frontend/package.json` and run the local bin.
