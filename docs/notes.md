# Notes: open questions and deferred ideas

## Ask at Base office hours
- Household mix (standard / medical / elderly / wfh): are these the categories that matter to Base, or are there others?
- Which ERCOT load zone do Base's homes sit in? We use `LZ_AEN`, but Austin Energy is municipal (not open to retail choice), so Base's Austin-area members may be in Oncor/PEC territory and a different zone.

## Data findings
- RT prices: gridstatus 0.36 `get_rtm_spp(year)` loses `Settlement Point Type`, so each load zone's standard (LZ) and energy-weighted (LZEW) prices both come out as e.g. `LZ_AEN`, in random order. Gap: median $0.01, max $17.10 (Feb 15 02:15). Fixed by `scripts/fetch_prices.py` reading ERCOT directly; we use `LZ`. Optional: report upstream to gridstatus. Mention in README provenance.
- EEA timeline: the original spec had "Normal Feb 19 09:00"; ERCOT actually stepped down EEA3 → EEA2 (09:00) → EEA1 (10:00) → Normal (10:35). Sourced timeline in `EEA_TIMELINE` (`backend/data.py`). Mention in README provenance.
- Naive policy on real Uri prices (`uv run python -m scripts.run_replay`): LZ_AEN is ≥ $1,000 almost continuously from Feb 13 00:15 to Feb 18 (every zone and hub agrees) and never ≤ $30 until Feb 19. So the naive fleet exports down to the floor by ~01:15 Feb 13 (~$9.6k), can't recharge, and holds for six days; when outages hit Feb 15 02:00 all 200 outage homes are dark within ~2 hours. This is the pitch's "what a naive policy would have put at risk" number: it sold the backup reserve two days before the blackouts. A reserve-aware policy is the contrast. Pinned by `test_naive_baseline_sells_the_reserve_before_the_blackouts`.

## To do when we reach that step
- Recording for the deployed site: a tick is ~48 KiB of JSON at 500 homes (SoC/kW/MW sent unrounded so fleet stats add up exactly), so 672 ticks ≈ 32 MB. Round SoC/kW in the recording (and keep counts consistent) or compress/delta-encode it.
- Frontend visual pass: load the fonts named in `docs/design.md` (Inter Tight, JetBrains Mono); tonight the page falls back to system fonts.
- Frontend top bar: format `t` for people (e.g. "Feb 15 05:00 CT") instead of raw ISO.
- Scene lighting: `suncalc` vs ~30 lines of our own sun math; add a "hold light level" toggle if the day/night cycle distracts in the Loom recording.

## Deferred (do if time allows)
- Cache the parquet reads in `UriParquetSource` (currently read once per `frames()` call, i.e. per websocket session). Only if it ever shows up as slow. Building a sim takes ~15 ms and runs on the event loop at connect and reset; move it to a thread (`asyncio.to_thread`) if many sessions ever run at once.
- Serializer speed: step + serialize + JSON is ~1.9 ms/tick at 500 homes (mostly Pydantic building 500 `HomeState`s). Fine at 64 ticks/s; at 2,000+ homes consider `model_construct` or serializing straight from arrays.
- Physics invariants (e.g. `discharge` ⇒ grid up, `backup` ⇒ grid down, `charge` ⇒ grid up). Define once and reuse for sim tests and optionally the wire models, rather than duplicating.
- Recovery charging: the naive policy only charges at ≤ $30, and in the Uri window no price is that low until Feb 19, so homes that went dark stay at 0% after the grid returns Feb 18 12:00. Consider a "grid back and below floor → charge regardless of price" rule.
- TS generator deps: `gen_types` runs `json-schema-to-typescript` via `npx` (tool pinned, its deps not). If `--check` ever reports `types.ts` stale with only formatting diffs (a prettier release), make it a pinned devDependency in `frontend/package.json` and run the local bin.
