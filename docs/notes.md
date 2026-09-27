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
  - (That table was run before device faults, the outage offsets and the 2% kept tolerance; the one below supersedes it. Both were run selling headroom, the old behaviour: the default now keeps it, and the sweep below supersedes both.)
- Failover, seed 0, Feb 10–20, default call rules, with the 2% kept tolerance, rolling cuts on varied quarter hours, and greedy cover (`uv run python -m scripts.run_replay --contract-size F --fault-rate R`). Failovers are warned or silent: rolling cuts that land mid-call make both (half the homes warn, `outage_notice_frac`), and device faults are all silent. "Hard out" is homes with a hard device fault by Feb 20. 47 called ticks in every run.

  | Contract | Fault rate /home-h | Kept | Penalties | Warned | Silent | Uncovered | Cover p50 / max | Hard out | Dark home-h | Net revenue |
  |---|---|---|---|---|---|---|---|---|---|---|
  | 10% | 0.001 | 87.2% | $5,586 | 135 | 178 | 0 | 11 s / 11 s | 21 | 3,268 | −$214,461 |
  | 10% | 0.005 | 87.2% | $5,297 | 110 | 162 | 0 | 11 s / 11 s | 111 | 3,254 | −$214,536 |
  | 10% | 0.02 | 83.0% | $4,278 | 62 | 142 | 3 | 11 s / 11 s | 324 | 3,230 | −$215,186 |
  | 30% | 0.001 | 68.1% | $23,380 | 93 | 137 | 86 | 11 s / 11 s | 21 | 3,205 | −$233,655 |
  | 30% | 0.005 | 57.4% | $28,587 | 79 | 124 | 105 | 11 s / 11 s | 111 | 3,197 | −$241,550 |
  | 30% | 0.02 | 40.4% | $63,154 | 44 | 107 | 119 | 11 s / 11 s | 324 | 3,177 | −$275,235 |
  | 60% | 0.001 | 44.7% | $116,284 | 93 | 137 | 230 | n/a (none covered) | 21 | 3,160 | −$352,415 |
  | 60% | 0.005 | 40.4% | $133,589 | 79 | 123 | 199 | 11 s / 11 s | 111 | 3,163 | −$367,471 |
  | 60% | 0.02 | 19.1% | $188,926 | 44 | 105 | 133 | 11 s / 11 s | 324 | 3,164 | −$409,045 |

  - Most failovers now come from the rolling outage, not device faults: a group cut mid-call drops ~90 homes at once. That's why the counts barely depend on the fault rate, and why they fall as it rises (hard-faulted homes get no call share, so fewer share holders are left to drop out).
  - Warned cover takes 5 s and silent 11 s. Silent failovers outnumber warned ones (the outage's silent half plus every device fault), so p50 = max = 11 s. It's under the 60 s KPI everywhere.
  - At 10% the buffer covers every failover but 3, and with the tolerance an 11 s gap no longer costs the interval: kept stays at 83–87% across fault rates. The misses left are the storm days when the fleet's energy runs out (Feb 15–16), as before.
  - At 30% and above the buffer can't cover a group cut: 86–119 uncovered at 30%, 133–230 at 60%. At 60% during the outage each on-grid home's share is already at max kW, so there's no spare power at all; the few 60% failovers that were covered (at 0.005 and 0.02) all happened outside the outage (Feb 11–14, Feb 19).
  - Greedy cover takes 1 home per failover (median) at 10%, 2 at 30% (at most 10).
  - Hard faults pile up over the 10 days: 21 homes (4%) by Feb 20 at 0.001, 111 (22%) at 0.005, 324 (65%) at 0.02. Those homes can't export, so they keep their energy for backup: dark home-hours fall slightly as the fault rate rises.
- Insight sweep (`uv run python -m scripts.sweep` → `results/sweep.csv`, 72 runs, ~30 s), headroom kept (the new default). Windows: pre-storm Feb 10 00:00 – Feb 13 00:00 (5 called ticks), storm Feb 14 00:00 – Feb 19 00:00 (30 called ticks); 47 in the whole replay. Promise kept, % (mean over seeds 0–2):

  | Contract | 0.001: pre-storm | storm | all | 0.005: pre-storm | storm | all |
  |---|---|---|---|---|---|---|
  | 10% | 100 | 95.6 | 97.2 | 100 | 94.4 | 96.5 |
  | 20% | 100 | 88.9 | 92.9 | 100 | 84.4 | 90.1 |
  | 30% | 100 | 66.7 | 78.7 | 100 | 53.3 | 70.2 |
  | 40% | 100 | 40.0 | 61.7 | 100 | 34.4 | 58.2 |
  | 60% | 100 | 20.0 | 45.4 | 100 | 18.9 | 41.8 |

  One knob at a time, fault rate 0.001, mean over seeds ($ and home-h are replay totals except storm dark home-h):

  | Contract | Variant | Called | Kept pre / storm / all | Penalties | Storm dark home-h | Headroom MWh avg | Reserve recharge | Net revenue |
  |---|---|---|---|---|---|---|---|---|
  | 10% | default ($1,000, 8 h, pre-charge on, keep) | 47 | 100 / 95.6 / 97.2 | $864 | 3,215 | 5.1 | $119,711 | −$223,413 |
  | 10% | trigger $500 | 54 | 100 / 95.6 / 97.5 | $865 | 3,215 | 5.1 | $119,750 | −$222,912 |
  | 10% | trigger $3,000 | 39 | 100 / 94.9 / 96.6 | $821 | 3,180 | 5.4 | $118,044 | −$211,979 |
  | 10% | standard backup 4 h | 47 | 100 / 95.6 / 97.2 | $1,078 | 3,227 | 6.9 | $93,646 | −$197,666 |
  | 10% | standard backup 12 h | 47 | 100 / 87.8 / 92.2 | $2,093 | 3,160 | 3.5 | $171,273 | −$242,839 |
  | 10% | pre-charge off | 47 | 100 / 95.6 / 97.2 | $872 | 3,218 | 5.1 | $119,807 | −$224,154 |
  | 10% | skip before storm | 23 | 100 / 100 / 100 | $8 | 3,187 | 5.3 | $118,679 | −$222,473 |
  | 10% | sell headroom | 47 | 100 / 84.4 / 90.1 | $4,104 | 3,260 | 3.7 | $151,865 | −$209,432 |
  | 30% | default | 47 | 100 / 66.7 / 78.7 | $17,374 | 3,188 | 5.9 | $78,132 | −$249,904 |
  | 30% | trigger $500 | 54 | 100 / 66.7 / 81.5 | $17,374 | 3,188 | 5.8 | $78,134 | −$247,408 |
  | 30% | trigger $3,000 | 39 | 100 / 61.5 / 74.4 | $17,374 | 3,188 | 6.0 | $78,112 | −$237,633 |
  | 30% | standard backup 4 h | 47 | 100 / 87.8 / 92.2 | $6,333 | 3,350 | 7.8 | $38,523 | −$227,807 |
  | 30% | standard backup 12 h | 47 | 100 / 30.0 / 53.2 | $47,007 | 3,132 | 3.9 | $164,844 | −$288,656 |
  | 30% | pre-charge off | 47 | 100 / 66.7 / 78.7 | $17,374 | 3,189 | 5.6 | $78,168 | −$251,543 |
  | 30% | skip before storm | 23 | 100 / 77.8 / 88.4 | $3,769 | 3,188 | 6.0 | $76,442 | −$250,219 |
  | 30% | sell headroom | 47 | 100 / 64.4 / 77.3 | $18,675 | 3,188 | 5.3 | $84,168 | −$228,182 |

  - Pre-storm, every size keeps 100%, but on only 5 called ticks. In the storm no size reaches the 99% bar by default: 10% comes closest (95.6%), and only 10% with `skip_before_storm` keeps everything (it calls 12 storm ticks instead of 30). The safe size drops from ≥ 60% before the storm to below 10% in it.
  - Keeping headroom is what lifts 10% from 84% to 96% kept in the storm (penalties $4.1k → $0.9k): sold headroom (37 MWh at 10%) is energy the Feb 15–16 calls then lack. It costs ~$14k of net revenue at 10% and ~$22k at 30%. At 30% it barely changes kept (64 → 67%): there the limit is spare power to cover group cuts (67 uncovered storm failovers), not energy.
  - The homeowner contract is the biggest lever: standard backup 4 h instead of 8 h lifts 30% to 88% kept in the storm and saves ~$22k, for 162 more dark home-hours in the storm; 12 h drops it to 30%. It sets how much energy the reserve locks up exactly when the calls come.
  - Reserve recharge (buying back up to the export floor as the forecast gets colder) is the largest cost: $78–126k of the loss. It falls from 10% to 30% (likely because the bigger call-ready energy above the reserve absorbs the colder forecast's higher reserve) and rises with the fault rate.
  - The trigger price barely matters: the storm has 30 called ticks at $500 and $1,000 and 26 at $3,000 (the price is above $3,000 for most of it); the trigger mostly adds or removes pre-storm and Feb 13/19 calls. Pre-charge does nothing when headroom is kept: the fleet fills at ≤ $30 on Feb 10 and never sells, so it's full by Feb 13 either way.
  - Uncovered storm failovers (mean per run, fault rate 0.001 / 0.005): 0 / 0 at 10%, 0.3 / 16 at 20%, 67 / 70 at 30%, 131 / 149 at 40%, 170 / 151 at 60%. Cover takes 8–11 s (p50), 11 s max.
  - Critical homes that ran out: 2, 5 and 5 (seeds 0, 1, 2) in every run, whatever the knobs. All are never-restored homes, out on Feb 15: a 16 h reserve can't last a 4-day outage. See the follow-up below.
  - Charts (`uv run python -m scripts.plots`, from `results/sweep.csv`):

    ![Promise kept vs contract size, pre-storm and storm](img/safe-contract.png)
    Pre-storm every contract size keeps 100% of its calls; in the storm, promise kept falls from 95.6% at 10% to 20% at 60%.

    ![Storm promise kept by standard backup hours at 10% and 30%](img/backup-vs-promise.png)
    Cutting standard backup from 8 h to 4 h lifts storm promise kept at 30% from 67% to 88% and halves the reserve recharge bill, at the cost of 162 more dark home-hours in the storm.
- Safe contract endpoint (`GET /api/safe-contract`, `backend/safe_contract.py`): contract 5–60% in steps of 5, plus no contract, × seeds 0–2, in a process pool. On this 16-core machine it takes 4.6 s with a cold pool (worker start-up), 3.0 s warm at 500 homes, 5.8 s warm at 2,000 homes (`MAX_HOMES`), and ~0 when cached. With the defaults, safe = 10% (storm kept 95.6%; 15% keeps 92.2%). With standard backup 4 h it's 20%, and with headroom sold none qualifies. The critical-homes half of the rule never binds today: every contract runs out 4.0 critical homes on average, the same as no contract (the never-restored ones, see below).
- Money split (`FleetStats`): `revenue_usd` = `contract_pnl_usd` − `backup_cost_usd` + `market_usd`. At 10% / 30% (seed 0) that's −$226k = $45k − $271k − $0.3k and −$253k = $98k − $351k − $0.4k: with headroom kept, the market line is ~0 and backup is the whole loss.
- Rolling outages (⚠ assumption): ERCOT and the utilities intended short rotating outages, but many circuits stayed out for days (critical-load circuits exempted, the sheer volume of load shed, ice damage). `RollingOutage` models both: 10% of homes never restored for the whole window, the rest cycling 4 h off / 6 h on in 5 groups, each group's cycle shifted by a seeded 0–7 ticks so cuts land on varied quarter hours (46% of the fleet out on average, 1–3 groups at a time). The durations and shares are our assumptions, not sourced; say so in the README.
- Household drain (⚠ assumption): lowered from ~7 kW to ~2.5 kW at 13 °F so a full average battery lasts ~12 h on backup (homes shed load on backup; reasoning in `FleetConfig`). No single value makes both battery sizes last 10–14 h (25 kWh needs ≤ 2.5 kW, 39.2 kWh needs ≥ 2.8 kW).

## To do when we reach that step
- Recording for the deployed site: a tick is ~48 KiB of JSON at 500 homes (SoC/kW/MW sent unrounded so fleet stats add up exactly), so 960 ticks ≈ 46 MB. Round SoC/kW in the recording (and keep counts consistent) or compress/delta-encode it.
- Frontend visual pass: load the fonts named in `docs/design.md` (Inter Tight, JetBrains Mono); tonight the page falls back to system fonts.
- Map, for now: the night basemap (`frontend/src/basemap.ts`) is OpenFreeMap's "dark" style with most layers dropped and the rest repainted; its palette is fixed, since scene lighting (day/night from the sim clock) isn't built. Still to do from design.md "The scene": the pinned landmark labels (Capitol, Congress Ave Bridge, Frost Bank Tower, Lady Bird Lake), the medical-home ring, and the blue pulse on exporting homes (homes have a static glow). 3D buildings only show from zoom 13; the fleet framing sits near zoom 10.5, so they appear when you zoom in. The dot colours are read from the CSS tokens once when the map loads, so a theme switch would need to re-apply the circle paint.
- Home boxes (3D view) sit at the homes' synthetic lat/lon, so some cut into real OSM buildings. Fine at a glance; if it bothers anyone, hide basemap buildings within ~10 m of a home or snap homes to building centroids in the backend. In 3D, dark by contract (dim grey) is brighter than dark (near-black), the reverse of the dots' rings; that's as specified, so a home that ran out reads as gone.
- Failover rings on the map: warned is one ring, silent a double ring; the failover log marks them ▲ and ○. Match the log's markers to the rings if the mismatch confuses anyone. Rings run on real time (1 s) and redraw the ring source every frame while any is showing; fine for a group cut of ~90 homes, revisit only if it stutters.
- Chart markers: the $1,000 sell threshold and the Feb 15 02:00 outage start are copied into `frontend/src/Charts.tsx` from `backend/policy.py` and `backend/faults.py`, because the wire doesn't carry them. When policies or outages become swappable, send them in `init` (a schema change) and drop the copies.
- `failovers_*` counts and p50/max are cumulative over the replay; per-tick detail is the `failovers` event list. `promise_kept` is a 0–1 fraction (not ×100).
- Promise kept counts an interval as kept within 2% of the promise (`kept_tolerance`, ⚠ ours). ADER's compliance deadband is 2 MW, far looser: at 3.6 MW it would forgive more than half the promise. The penalty still charges the whole shortfall. Revisit if Base knows the tolerance in its utility contracts.
- A cover due after the tick ends (a silent drop-out in the last 11 s) counts as covered in 11 s, with the rest of the tick uncovered; next tick's plan takes over.
- Device faults: a faulted home can't discharge but still backs up its own house and can still charge (the local controller runs on). Faults hit every home at the same rate, on or off grid, calls or not; hard ones accumulate from Feb 10. NaivePolicy doesn't split calls (`Decisions.call_kw` None), so it gets no failovers: its faulted homes just stop exporting.
- The sim asks the grid faults about the next tick, to warn homes ahead of an outage. A `Fault` must be a function of the time alone (both current faults are).
- Forecast: `forecast_min_f` (`backend/sim.py`) is perfect foresight (the actual temperatures). The forecast error model replaces that one function.
- ContractPolicy plans the next call's share pro rata to room above the reserve among on-grid homes, so shares move as homes lose or regain grid. Call-ready recharge is skipped during a call (only the reserve is recovered), because `delivered_mw` counts exports only and charging would otherwise inflate promise kept.
- `UtilityContract` counts calls per Central-time day, not "one per day on average" (GVEC's wording), and doesn't track Austin Energy's 40 events a year: irrelevant for a 10-day replay, but it matters for a season-long one. Calls trigger on price only. The grid-emergency trigger (ERCOT ERS deploys on reserves < 3,000 MW, not price) isn't built.
- `headroom_mwh` is energy above the contract reserve, fleet total (per the build brief, docstring updated to match). It includes tier `none` homes' energy below the 20% export floor, which can't be exported (~0.3 MWh through the storm), and during a call it includes what the rest of the call will draw.
- `delivered_mw` (and so promise kept and the penalty) counts exports only. Homes recharging to their reserve during a call aren't netted against it.
- HUD: playback (play/pause, speed, reset) lives in the top bar for now; design.md's bottom timeline with a scrubber waits on `seek`. The top bar dropped the "tick N/960" readout to fit at 1440 px; temperature stays. A panel's expanded state isn't persisted (a reload comes back docked), which is deliberate. Saved panel positions from before the HUD pass may overlap the new top bar; clear `simuritor.*` in localStorage to get the defaults.
- Critical homes that ran out is never 0 in the sweep, because the never-restored 10% includes 2–5 critical homes and no 16 h reserve lasts ~4 days. So the "no critical home runs out" bar for the safe contract size can't be met under this outage model, whatever the contract. Options: count only rotating homes for the bar, report never-restored ones separately, or let critical homes keep more (e.g. no call share once off grid for long). Decide before the README charts.
- The pre-storm window has only 5 called ticks per run, so its 100% kept is thin evidence. Say so when comparing windows, or widen the window (Feb 13 has 12 of the rest).
- `headroom_sold_mwh` counts exports beyond each home's call share (all exports outside calls), so for NaivePolicy it's everything it sells. Reserve recharge cost counts any import that brings a home up to its export floor (contract reserve or 20%), whatever the policy meant by it.
- `results/sweep.csv` is script output, committed (32 KB) so the charts are reproducible without rerunning the sweep: regenerate it with `scripts/sweep.py`, then the charts with `scripts/plots.py`; don't edit either by hand.
- Call energy in `contract_pnl_usd` is delivery up to the promise, at the interval price. Delivery beyond the promise (sold headroom during a call) is `market_usd`. This split is settlement-style (it doesn't care which home exported what), so it can differ slightly from `headroom_sold_mwh` when a call is short and headroom is being sold at the same time.
- `backup_cost_usd` counts charging up to the policy's refill level (`Decisions.refill_kwh`): for ContractPolicy that's the reserve plus, outside calls, call-ready; for NaivePolicy it's the 20% floor. That makes it 2–4× the sweep's `reserve_recharge_usd`, which stops at the export floor ($271k vs $120k at 10%, $351k vs $82k at 30%). The sweep CSV and the backup chart still use the narrower number, labelled "reserve recharge"; rerun both if the README should quote backup cost instead.
- The safe rule's kept bar is 95% (the endpoint and the chart); the earlier plan in `docs/dispatch-design.md` said 99%. It's `SAFE_KEPT` in `backend/safe_contract.py`. A contract with no storm calls counts as kept.
- `/api/safe-contract` notes:
  - The cache is in-process: an LRU of 64 entries, not shared across uvicorn workers, and two identical requests in flight both compute.
  - The worker pool is spawned (the server runs threads) on the first request, so that request pays ~1.5 s of start-up. Warm it in the lifespan if that shows.
  - The Vite dev proxy only forwards `/ws`, so the frontend needs `/api` added before it can call the endpoint.
  - The deployed static site can't call it at all: ship precomputed JSON for the default params, or cut the feature there.
- Replay params: `/ws?policy=naive&contract=0.1…` replaced the `SIMURITOR_POLICY` env var. `ReplayParams.contract` defaults to 30%, while `UtilityContract.size_frac` (used by `run_replay` and the sim tests) still defaults to 60%. Align them if that confuses.
- Scene lighting: `suncalc` vs ~30 lines of our own sun math; add a "hold light level" toggle if the day/night cycle distracts in the Loom recording.

## Deferred (do if time allows)
- Frontend bundle: MapLibre and Recharts make the main JS chunk ~1.6 MB (450 kB gzipped) plus a ~510 kB worker (the two share code Vite bundles twice), and `npm run build` warns about chunk size. Lazy-load the map or split chunks only if first load feels slow on the deployed site.
- Cache the parquet reads in `UriParquetSource` (currently read once per `frames()` call, i.e. per websocket session). Only if it ever shows up as slow. Building a sim takes ~15 ms and runs on the event loop at connect and reset; move it to a thread (`asyncio.to_thread`) if many sessions ever run at once.
- Serializer speed: step + serialize + JSON is ~1.9 ms/tick at 500 homes (mostly Pydantic building 500 `HomeState`s). Fine at 64 ticks/s; at 2,000+ homes consider `model_construct` or serializing straight from arrays.
- Physics invariants (e.g. `discharge` ⇒ grid up, `backup` ⇒ grid down, `charge` ⇒ grid up). Define once and reuse for sim tests and optionally the wire models, rather than duplicating.
- TS generator deps: `gen_types` runs `json-schema-to-typescript` via `npx` (tool pinned, its deps not). If `--check` ever reports `types.ts` stale with only formatting diffs (a prettier release), make it a pinned devDependency in `frontend/package.json` and run the local bin.
