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
- Insight sweep (`uv run python -m scripts.sweep` → `results/sweep.csv`, 102 runs of 3,000 homes, ~19 s on a 16-thread pool). Homes on real Austin building sites, outages by feeder (both below), headroom kept. Uri windows: pre-storm Feb 10 00:00 – Feb 13 00:00 (5 called ticks), storm Feb 14 00:00 – Feb 19 00:00 (30 called ticks); 47 in the whole replay. The normal winter week (Feb 21–27, 2022) has 6. Earlier tables (500 homes, random layout, homes cut one by one) are gone; they are in git history. Promise kept, % (mean over seeds 0–2):

  | Contract | 0.001: Uri pre-storm | Uri storm | Uri all | normal week | 0.005: Uri pre-storm | Uri storm | Uri all | normal week |
  |---|---|---|---|---|---|---|---|---|
  | 10% | 100 | 97.8 | 98.6 | 100 | 100 | 97.8 | 98.6 | 100 |
  | 20% | 100 | 88.9 | 92.9 | 100 | 100 | 81.1 | 87.9 | 100 |
  | 30% | 100 | 61.1 | 75.2 | 100 | 100 | 53.3 | 70.2 | 100 |
  | 40% | 100 | 43.3 | 63.8 | 100 | 100 | 35.6 | 58.9 | 100 |
  | 60% | 100 | 23.3 | 48.9 | 100 | 100 | 20.0 | 42.6 | 100 |

  Uri, one knob at a time, fault rate 0.001, mean over seeds ($ and home-h are replay totals except storm dark home-h):

  | Contract | Variant | Called | Kept pre / storm / all | Penalties | Storm dark home-h | Headroom MWh avg | Reserve recharge | Net revenue |
  |---|---|---|---|---|---|---|---|---|
  | 10% | default ($1,000, 8 h, pre-charge on, keep) | 47 | 100 / 97.8 / 98.6 | $2,185 | 19,900 | 30.6 | $711,377 | −$1,337,793 |
  | 10% | trigger $500 | 54 | 100 / 97.8 / 98.8 | $2,234 | 19,905 | 30.4 | $711,613 | −$1,334,881 |
  | 10% | trigger $3,000 | 39 | 100 / 98.7 / 99.1 | $659 | 19,675 | 32.3 | $701,053 | −$1,268,547 |
  | 10% | standard backup 4 h | 47 | 100 / 100 / 100 | $70 | 19,969 | 41.6 | $550,250 | −$1,176,272 |
  | 10% | standard backup 12 h | 47 | 100 / 88.9 / 92.9 | $11,016 | 19,559 | 20.8 | $1,019,937 | −$1,454,656 |
  | 10% | pre-charge off | 47 | 100 / 97.8 / 98.6 | $2,589 | 19,918 | 30.4 | $711,919 | −$1,342,167 |
  | 10% | skip before storm | 23 | 100 / 100 / 100 | $37 | 19,719 | 31.7 | $701,982 | −$1,337,897 |
  | 10% | sell headroom | 47 | 100 / 86.7 / 91.5 | $21,618 | 20,194 | 21.9 | $896,635 | −$1,251,321 |
  | 30% | default | 47 | 100 / 61.1 / 75.2 | $106,428 | 19,740 | 35.4 | $465,527 | −$1,510,056 |
  | 30% | trigger $500 | 54 | 100 / 61.1 / 78.4 | $106,428 | 19,740 | 34.9 | $465,529 | −$1,495,055 |
  | 30% | trigger $3,000 | 39 | 100 / 55.1 / 70.1 | $106,428 | 19,739 | 36.3 | $465,319 | −$1,436,004 |
  | 30% | standard backup 4 h | 47 | 100 / 85.6 / 90.8 | $33,401 | 20,734 | 46.9 | $224,993 | −$1,367,982 |
  | 30% | standard backup 12 h | 47 | 100 / 33.3 / 56.7 | $268,272 | 19,379 | 23.3 | $981,515 | −$1,723,252 |
  | 30% | pre-charge off | 47 | 100 / 61.1 / 75.2 | $106,428 | 19,744 | 33.5 | $465,927 | −$1,519,905 |
  | 30% | skip before storm | 23 | 100 / 75.0 / 87.0 | $19,594 | 19,740 | 36.0 | $460,701 | −$1,498,685 |
  | 30% | sell headroom | 47 | 100 / 58.9 / 73.8 | $118,704 | 19,742 | 31.6 | $498,082 | −$1,383,023 |

  - In a normal week every size keeps 100% of its calls, with no uncovered failover: the fleet is on grid and full, and the one call (Feb 24 06:15–07:45) asks for 1.5 h. Uri's storm is what sizes the contract: only 10% stays above 95% by default (97.8%), and it falls to 23% at 60%. Pre-storm stays at 100% at every size too, on 5 called ticks.
  - The findings from the 500-home sweep hold at 3,000 homes with feeder outages. Keeping headroom beats selling it at 10% (97.8% vs 86.7% storm kept, penalties $2k vs $22k), though selling earns ~$86k more. A 4 h standard reserve instead of 8 h lifts 30% to 86% storm kept and cuts reserve recharge from $466k to $225k, for ~1,000 more storm dark home-hours; 12 h drops it to 33%. The trigger price and pre-charge barely matter.
  - Storm failovers (mean per run, fault rate 0.001 / 0.005): uncovered 0 / 1 at 10%, 0 / 30 at 20%, 292 / 480 at 30%, 795 / 778 at 40%, 928 / 831 at 60%. Feeder cuts drop whole neighbourhoods mid-call (a group is ~540 homes), so from 30% up the buffer can't cover them. Cover p50 7–11 s, max 11 s.
  - Critical homes that ran out: 37, 36 and 26 (seeds 0, 1, 2) in every Uri run, whatever the knobs, and every one is in a never-restored feeder (all of that feeder's critical homes run out). Feeders concentrate it: the never-restored set is 3–6 whole feeders (281–336 homes), so the count swings more by seed than with homes cut one by one. None in the normal week. See the follow-up below.
  - The normal week pays: net revenue rises with the contract to $65.7k at 40% ($17k at 10%), then falls to $37k at 60%. The capacity payment grows linearly, but so does call-ready recharge after the Feb 24 call: the price stays at $2,000–4,000 until 10:15, and the policy buys the next call's energy back whatever the price, although the daily cap means no second call can come that day. It is booked to the contract (`contract_pnl_usd`). See the follow-up below.
  - Charts (`uv run python -m scripts.plots`, from `results/sweep.csv`):

    ![Promise kept vs contract size: normal winter week, Uri pre-storm and storm](img/safe-contract.png)
    A normal winter week and Uri's pre-storm days keep 100% of calls at every contract size; in Uri's storm promise kept falls from 97.8% at 10% to 23% at 60%.

    ![Storm promise kept by standard backup hours at 10% and 30%](img/backup-vs-promise.png)
    Cutting standard backup from 8 h to 4 h lifts storm promise kept at 30% from 61% to 86% and halves the reserve recharge bill ($466k → $225k), for ~1,000 more dark home-hours in the storm.
- Failure domains (`spread_by_domain`, ⚠ assumes the operator knows the utility's rotation blocks): each rotating-outage group is a domain, and the never-restored feeders are one more. A call is split evenly across the on-grid domains, then pro rata to charge inside each one. The buffer is N-1: losing the domain with the largest share leaves that share spare on the other domains. That is a buffer fraction of largest / (total − largest): 1/2 with 3 even domains, 1/4 with 5, and all of it with 2. It replaces the fixed 20%, which is also how the next call's call-ready energy is sized. Uri, 3,000 homes, fault rate 0.001, seeds 0–2 (`scripts/sweep.py`, variant "spread by domain"; storm window except contract P&L, which covers the whole replay):

  | Contract | Spread | Storm kept | Uncovered failovers (per seed) | Cover p50 / max | Contract P&L |
  |---|---|---|---|---|---|
  | 10% | off | 97.8% | 0 | 7 / 11 s | −$625k |
  | 10% | on | **100%** | 0 | 7 / 11 s | −$767k |
  | 20% | off | 88.9% | 0 | 7 / 11 s | −$917k |
  | 20% | on | 88.9% | 0 | 7 / 11 s | −$960k |
  | 30% | off | 61.1% | 292 (524, 351, 2) | 9 / 11 s | −$1,042k |
  | 30% | on | 61.1% | 347 (382, 656, 2) | 9 / 11 s | −$1,058k |

  - It helps only at 10%, where it lifts seed 2 from 93.3% to 100% and cuts penalties from $2.2k to $60. At 20% and 30% storm kept doesn't move in any seed. At 20% no failover goes uncovered either way, so those misses are the fleet running short of energy, not failover, and no split fixes that. At 30% the uncovered count moves both ways by seed (−142, +305, 0) without changing a kept interval.
  - It costs contract P&L: the N-1 buffer is bigger than 20% during the storm (2–4 domains on grid, so 1/3 to all of the share), so homes charge more call-ready energy at storm prices (−$142k at 10%, −$15k at 30%). Backup cost falls by less than that, because homes already hold more energy when their reserve needs refilling. Net revenue is within 1%.
  - Safe contract with it on: still **15% in Uri** (storm kept 96.7% vs 95.6%; 20% still 88.9%) and 60% in the normal week.

    ![Storm promise kept and uncovered failovers, default split vs spread by outage block](img/failure-domains.png)
    Splitting calls by outage block lifts only the 10% contract (97.8% → 100% storm kept); at 20–30% storm kept is unchanged, and uncovered failovers at 30% vary more by seed than by split.
- Safe contract endpoint (`GET /api/safe-contract`, `backend/safe_contract.py`): per scenario (Uri, the normal week), contract 5–60% in steps of 5 plus no contract, × seeds 0–2: 78 replays in a process pool. At the defaults (3,000 homes) safe = **15% in Uri** (storm kept 95.6%; 20% keeps 88.9%) and **60% in the normal week** (everything is kept). With a 4 h standard reserve Uri's safe size is 25%; selling headroom, none qualifies. Timing on this machine (8 cores, 16 threads): 500 homes 6.2 s with a cold pool, 4.8 s warm; **3,000 homes 11–12 s warm, over the 10 s budget** (~80 s of single-core replay work and hyperthreading gives little). Cached repeats are instant. The app now warms the cache at startup, in the background, for the default params and the default params with the storm clause (`skip_before_storm`). The default answer is ready ~13 s after startup and the storm clause ~23 s (they share the pool); a request that arrives earlier waits for the running computation instead of starting a second one. Other params still take 11–14 s the first time; fewer seeds or a faster step would help (no single hot spot; the time is spread over 3,000-element numpy ops).
- Money split (`FleetStats`), 3,000 homes, seed 0. Call-ready recharge now counts against the contract, not backup, because it exists for the contract: charging up to the reserve is backup, and from the reserve up to call-ready is contract. Uri at 10% is −$1,333k = −$632k contract − $699k backup − $1.6k market; at 30%, −$1,519k = −$1,050k − $466k − $2.3k; no contract, −$1,301k (all backup). The normal week at 60%: +$36.8k = $36.9k − $0 − $0.1k. The totals are unchanged, only the attribution moved. In Uri the contract loses money at every size: in the default Uri runs (mean over seeds), capacity plus call energy is $273k at 10% and $720k at 30%, and call-ready recharge at ~$9,000/MWh is $896k and $1,655k.
- Rolling outages (⚠ assumption): ERCOT and the utilities intended short rotating outages, but many circuits stayed out for days (critical-load circuits exempted, the sheer volume of load shed, ice damage). `RollingOutage` models both, a feeder at a time: whole feeders totalling ~10% of homes are never restored for the whole window, and the rest cycle 4 h off / 6 h on in 5 groups of whole feeders, each group's cycle shifted by a seeded 0–7 ticks so cuts land on varied quarter hours (~46% of the fleet out on average, 1–3 groups at a time). The durations and shares are our assumptions, not sourced; say so in the README. Only the Uri scenario has outages; the normal week has device faults only.
- Feeders (⚠ assumption): a seeded k-means on home positions groups the fleet into 40 feeders (`backend.faults.feeders`, `FleetConfig.n_feeders`), a stand-in for the real distribution network. At 3,000 homes a feeder is 23–138 homes (median 74). Real Austin Energy feeders serve a few thousand customers each, so ours are smaller than real ones but the right shape: an outage takes a neighbourhood.
- Home sites: `data/austin_homes.parquet`, 50,000 of 186,367 residential buildings in the fleet's bounding box, a seeded sample (`scripts/fetch_homes.py`, one Overpass query, OSM data as of 2026-09-27). Austin's building import tags almost everything `building=yes`, so a home is a house-like building with a house number inside a `landuse=residential` area. That misses homes where residential land use isn't mapped, and admits some small non-homes (e.g. an addressed garage apartment); the map shows the gaps (the lake, downtown, commercial strips). Data © OpenStreetMap contributors, ODbL: credit it in the README and on the map. The fleet samples its homes from this file (seeded); without it they are placed uniformly at random as before.
- Normal winter week: Mon Feb 21 – Sun Feb 27, 2022 (`NormalWeekSource`). Jan–Feb 2022 had no EEA (ERCOT declared none between Uri and Sept 2023), so every week qualified on that. This is the only week whose LZ_AEN price reaches the $1,000 call trigger (Feb 23 23:15, outside the call window, and Feb 24 06:15–10:15, max $4,069), from a moderate cold front: lows ~27 °F against Uri's single digits, prices otherwise −$22 to $115. A truly ordinary week (e.g. Jan 10–16: mean 49.5 °F, no freezing hours, max $215) never calls the contract, so every size would be vacuously safe and the chart would have no line. Say so when quoting "normal". Prices from the 2022 ERCOT report (`scripts/fetch_prices.py normal`); temperatures from Open-Meteo's archive (`scripts/fetch_temps.py`), the same source as the Uri file (it reproduces it exactly).
- Scale (seed 0, 16-thread laptop; `ws` = uvicorn + a Python websocket client at speed 64, max 64 ticks/s):

  | Homes | Build | Headless step | Step + serialize + JSON | Tick size | `init` size | ws ticks/s |
  |---|---|---|---|---|---|---|
  | 500 | 40 ms | 0.41 ms/tick (0.4 s/replay) | 2.0 ms | 57 KiB | 52 KiB | 61 |
  | 3,000 | 145 ms | 1.06 ms/tick (1.0 s/replay) | 9.3 ms | 340 KiB | 310 KiB | 56 |
  | 10,000 | 553 ms | 3.27 ms/tick (3.1 s/replay) | 39 ms | 1,131 KiB | 1,032 KiB | 20–22 |

  3,000 homes streams at 56 ticks/s, well above 16, so it's now the served default (`ReplayParams.homes`; `run_replay` and the sweep follow it): 3,000 × 12 kW = 36 MW nameplate, about Base's 40 MW Austin Energy deal (40 MW at 12–17 kW per home is 2,400–3,300 homes). `FleetConfig.n_homes` stays 500, the sim's own default, so tests stay fast and their exact counts hold. `MAX_HOMES` is now 10,000. Not measured: the browser. At 3,000 homes and 16 ticks/s the frontend parses ~5.4 MB/s of JSON and repaints 3,000 map points per tick; check the map frame rate before the demo.
- Household drain (⚠ assumption): lowered from ~7 kW to ~2.5 kW at 13 °F so a full average battery lasts ~12 h on backup (homes shed load on backup; reasoning in `FleetConfig`). No single value makes both battery sizes last 10–14 h (25 kWh needs ≤ 2.5 kW, 39.2 kWh needs ≥ 2.8 kW).

## To do when we reach that step
- Recording for the deployed site: a tick is ~57 KiB of JSON at 500 homes and ~340 KiB at the new 3,000-home default (SoC/kW/MW sent unrounded so fleet stats add up exactly), so 960 ticks ≈ 320 MB. Round SoC/kW in the recording (and keep counts consistent), compress/delta-encode it, or record a smaller fleet.
- Frontend visual pass: load the fonts named in `docs/design.md` (Inter Tight, JetBrains Mono); tonight the page falls back to system fonts.
- Map visual pass: the basemap is the stock OpenFreeMap "liberty" style, hard-coded in `Map.tsx`; the design wants a muted style owned by the theme. The dot colours are read from the CSS tokens once when the map loads, so a theme switch would need to re-apply the circle paint.
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
- Critical homes that ran out is never 0 in Uri, because the never-restored feeders hold 26–37 of the 300 critical homes (3,000-home fleet) and no 16 h reserve lasts ~4 days. So the "no critical home runs out" bar for the safe contract size can't be met under this outage model, whatever the contract (the endpoint compares with no contract instead, and that half never binds). Options: count only rotating homes for the bar, report never-restored ones separately, or let critical homes keep more (e.g. no call share once off grid for long). Decide before the README charts.
- The pre-storm window has only 5 called ticks per run, and the normal week 6 (one call), so their 100% kept is thin evidence. Say so when comparing windows, or widen the window (Feb 13 has 12 of the rest).
- Call-ready recharge ignores the daily call cap: after the last call a day allows, the policy still buys the next call's energy back "whatever the price", even though no call can come until tomorrow. In the normal week that's the whole $65k call-ready cost at 60%, now in `contract_pnl_usd` (the Feb 24 price stays at $2,000–4,000 for 2 h after the call). Waiting for the price to fall when no call can come today (or until the window closes) would fix it; it needs the policy to see the calls left today (`Commitment`).
- Home sites: the Overpass query leans on `landuse=residential` being mapped. Where it isn't, homes are missing (the map shows it); a buildings-only query with a footprint-area filter would catch more, at the cost of commercial buildings. The fetch is one query (~20 s); Overpass answers 504 at once if the declared `timeout`/`maxsize` are too large, which is why they are the defaults.
- Scenario windows: `AustinParquetSource.TEST_WINDOW` is the storm for Uri and the whole week for `normal`; `PRE_WINDOW` exists only for Uri. The safe-contract point field is `kept` (was `storm_kept`) for that reason.
- `headroom_sold_mwh` counts exports beyond each home's call share (all exports outside calls), so for NaivePolicy it's everything it sells. Reserve recharge cost counts any import that brings a home up to its export floor (contract reserve or 20%), whatever the policy meant by it.
- `results/sweep.csv` is script output, committed (38 KB) so the charts are reproducible without rerunning the sweep: regenerate it with `scripts/sweep.py`, then the charts with `scripts/plots.py`; don't edit either by hand.
- Call energy in `contract_pnl_usd` is delivery up to the promise, at the interval price. Delivery beyond the promise (sold headroom during a call) is `market_usd`. This split is settlement-style (it doesn't care which home exported what), so it can differ slightly from `headroom_sold_mwh` when a call is short and headroom is being sold at the same time.
- `backup_cost_usd` counts charging up to the policy's refill level (`Decisions.refill_kwh`: the reserve, or for NaivePolicy the 20% floor). Charging from there up to `Decisions.call_ready_kwh` (ContractPolicy, outside calls) is a contract cost in `contract_pnl_usd`. For ContractPolicy, backup cost now equals the sweep's `reserve_recharge_usd` (both stop at the export floor), and the sweep CSV records both `backup_cost_usd` and `contract_pnl_usd`.
- Failure domains, follow-ups:
  - The N-1 buffer is our reading of "buffer = the largest domain's share": it is the spare the *other* domains hold, so losing that domain is fully covered. Taken literally, as a fleet total, the buffer spread over every domain would leave only (D−1)/D of it once the largest is lost.
  - With one domain on grid, nothing else can cover it, so the buffer falls back to 20%. With two, the buffer is the whole share (each home plans for twice its share), which is what drives the call-ready cost up in the storm.
  - `build_replay` builds the rotation blocks in every scenario, so the policy has domains in the normal week too (6 domains: the buffer works out to 20%, the same as the default). Nothing rotates there.
  - The domain map is perfect knowledge of the utility's blocks. A real operator may know feeders but not the rotation order; a test with a noisy or partial map would say how much the result depends on it.
  - Spreading doesn't target the real storm problem, which is energy (20% misses with no uncovered failover). Aiming the split at homes that will stay on grid for the rest of the call (the rotation schedule, not only the blocks) is the next thing to try.
- The safe rule's kept bar is 95% (the endpoint and the chart); the earlier plan in `docs/dispatch-design.md` said 99%. It's `SAFE_KEPT` in `backend/safe_contract.py`. A contract with no storm calls counts as kept.
- The websocket handler runs its send and receive halves in an anyio task group (was two bare `asyncio` tasks). With bare tasks, a handler cancelled mid-`asyncio.wait` (the test client closes the socket and cancels the app straight away) orphaned both halves, and `test_ws_query_params_set_the_replay_and_init_echoes_them` failed ~1 run in 6 under CPU load (`CancelledError` on close). 0 in 40 since. `anyio` is now a declared dependency (it came in through Starlette).
- `/api/safe-contract` notes:
  - The cache is in-process: an LRU of 64 computations (running or finished), not shared across uvicorn workers. Identical requests in flight share one computation; a failed one is retried by the next request.
  - The startup warm-up keeps all 16 workers busy for ~23 s, so a request for other params in that window queues behind it. `--reload` restarts pay it again on every save; set `WARM_SAFE_CONTRACT = ()` locally if that gets in the way.
  - The Vite dev proxy only forwards `/ws`, so the frontend needs `/api` added before it can call the endpoint.
  - The deployed static site can't call it at all: ship precomputed JSON for the default params, or cut the feature there.
- Replay params: `/ws?policy=naive&contract=0.1&scenario=normal…` replaced the `SIMURITOR_POLICY` env var. `run_replay` and the sweep now default to the served replay (`ReplayParams`: 3,000 homes, 30%); the sim's own defaults (`FleetConfig.n_homes` 500, `UtilityContract.size_frac` 60%) are what the sim tests use. Align them if that confuses.
- Scene lighting: `suncalc` vs ~30 lines of our own sun math; add a "hold light level" toggle if the day/night cycle distracts in the Loom recording.

## Deferred (do if time allows)
- Frontend bundle: MapLibre and Recharts make the main JS chunk ~1.6 MB (450 kB gzipped) plus a ~510 kB worker (the two share code Vite bundles twice), and `npm run build` warns about chunk size. Lazy-load the map or split chunks only if first load feels slow on the deployed site.
- Cache the parquet reads in `UriParquetSource` (currently read once per `frames()` call, i.e. per websocket session). Only if it ever shows up as slow. Building a sim takes ~15 ms and runs on the event loop at connect and reset; move it to a thread (`asyncio.to_thread`) if many sessions ever run at once.
- Serializer speed: step + serialize + JSON is ~1.9 ms/tick at 500 homes (mostly Pydantic building 500 `HomeState`s). Fine at 64 ticks/s; at 2,000+ homes consider `model_construct` or serializing straight from arrays.
- Physics invariants (e.g. `discharge` ⇒ grid up, `backup` ⇒ grid down, `charge` ⇒ grid up). Define once and reuse for sim tests and optionally the wire models, rather than duplicating.
- TS generator deps: `gen_types` runs `json-schema-to-typescript` via `npx` (tool pinned, its deps not). If `--check` ever reports `types.ts` stale with only formatting diffs (a prettier release), make it a pinned devDependency in `frontend/package.json` and run the local bin.
