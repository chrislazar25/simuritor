# Notes: open questions and deferred ideas

## Ask at Base office hours
- Household mix (standard / medical / elderly / wfh): are these the categories that matter to Base, or are there others?
- Which ERCOT load zone do Base's homes sit in? We use `LZ_AEN`, but Austin Energy is municipal (not open to retail choice), so Base's Austin-area members may be in Oncor/PEC territory and a different zone.

## Data findings
- RT prices: gridstatus 0.36 `get_rtm_spp(year)` loses `Settlement Point Type`, so each load zone's standard (LZ) and energy-weighted (LZEW) prices both come out as e.g. `LZ_AEN`, in random order. Gap: median $0.01, max $17.10 (Feb 15 02:15). Fixed by `scripts/fetch_prices.py` reading ERCOT directly; we use `LZ`. Optional: report upstream to gridstatus. Mention in README provenance.
- EEA timeline: the original spec had "Normal Feb 19 09:00"; ERCOT actually stepped down EEA3 → EEA2 (09:00) → EEA1 (10:00) → Normal (10:35). Sourced timeline in `EEA_TIMELINE` (`backend/data.py`). Mention in README provenance.

## To do when we reach that step
- Serializer: round floats for the wire (interpolated temps come out like `27.549999999999997`). Round only there, not in the data layer or sim; pick precisions then.
- Frontend visual pass: load the fonts named in `docs/design.md` (Inter Tight, JetBrains Mono); tonight the page falls back to system fonts.
- Frontend top bar: format `t` for people (e.g. "Feb 15 05:00 CT") instead of raw ISO.
- Scene lighting: `suncalc` vs ~30 lines of our own sun math; add a "hold light level" toggle if the day/night cycle distracts in the Loom recording.

## Deferred (do if time allows)
- Cache the parquet reads in `UriParquetSource` (currently read once per `frames()` call, i.e. per websocket session). Only if it ever shows up as slow.
- Physics invariants (e.g. `discharge` ⇒ grid up, `backup` ⇒ grid down, `charge` ⇒ grid up). Define once and reuse for sim tests and optionally the wire models, rather than duplicating.
- Recovery charging: the naive policy only charges at ≤ $30, so a home that went dark stays near 0% after the grid returns while prices are still extreme. Consider a "grid back and below floor → charge regardless of price" rule.
- TS generator deps: `gen_types` runs `json-schema-to-typescript` via `npx` (tool pinned, its deps not). If `--check` ever reports `types.ts` stale with only formatting diffs (a prettier release), make it a pinned devDependency in `frontend/package.json` and run the local bin.
