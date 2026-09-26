# Dispatch design: contracts, headroom, failover

Status: **locked Sat Sep 26, 14:53.** Replaces the "rules + Jev for the judgment calls" plan. The dispatch policy is deterministic; the hard part, and the product, is keeping the fleet's promises when batteries fail.

## The question Simuritor answers
> **How many MW per home can Base safely promise a utility if the next Uri happens?**

The one knob is **contract size as a % of fleet nameplate power**. A bigger contract earns more capacity revenue but leaves less room to cover failed batteries. The insight compares the safe contract size in the pre-storm days against the storm itself.

## Two contracts, one fleet
Every battery's energy is split into layers, filled bottom-up:

```
┌──────────────┐ 100%
│ HEADROOM     │  uncommitted: used for extra exports, on-site loads, or kept
├──────────────┤
│ BUFFER       │  held back so healthy homes can cover failed ones
├──────────────┤
│ UTILITY      │  the MW promised to the utility during a call
├──────────────┤
│ HOME RESERVE │  untouchable; set by the home's tier
└──────────────┘ 0%
```

### Homeowner contract: tiers (configurable)
| Tier | Default share | Reserve |
|---|---|---|
| `none` | 10% | 0. The homeowner accepts outages. |
| `standard` | 80% | enough for **8 h** of backup |
| `critical` | 10% (the `medical` households) | enough for **16 h** of backup; never touched |

- Reserve is set in **hours, not %**: `reserve_kWh = hours × drain_kW(forecast temp)`, capped at capacity. The colder the forecast, the less energy there is to sell, and it's coldest exactly when prices peak.
- Off grid + tier `none`: the home goes **dark by contract**. The battery can't export while islanded, so its energy stays as headroom (usable on site, or exported once the grid returns). A goodwill policy that powers these homes anyway is a later add-on.
- **Dark by contract** is counted separately from **dark, ran out**. Only the second is a failure.

### Utility contract (modelled on Base's utility deals)
- Size = **contract % × fleet nameplate** (default 60% of 500 × 12 kW = 3.6 MW).
- **Called when price ≥ $1,000/MWh**, for at most **1.5 h (6 ticks)** per call, then a **2 h cooldown**. The trigger can be configured to EEA or both.
- At most **one call per day** (Central time; `max_calls_per_day`), and only **06:00–22:00**. A call still running at 22:00 ends.
- Two flags, both off by default:
  - `skip_before_storm`: no call while the forecast minimum over the next 24 h is below 20°F, so batteries stay full for backup.
  - `emergency_uncapped` (the stress case): during an EEA a call may start whatever the daily limit says, and it doesn't count against it.
- Paid two ways:
  - a **capacity payment** ($/MW-week, whether or not it's called; default $2,000/MW-week ≈ $100/kW-yr, in the range of a peaker's cost of new entry);
  - energy delivered during a call, paid at the interval price.
- **Shortfall** (delivered < promised) is charged at the interval price. That's the penalty. Missed intervals are also counted, because repeated misses are what get an aggregator's qualification revoked.

## The policy: a fixed priority list, per home, per 15-min tick
1. **Off grid?** Tiers `standard`/`critical` power the house from the battery. Tier `none` goes dark and keeps its energy.
2. **Protect the reserve** (tier × forecast temperature). Exports also stop at the fleet's reserve floor (20% SoC, the battery's minimum operating SoC), so a home's export floor is whichever is higher.
3. **Utility call active?** Deliver the contracted MW. Split it across on-grid homes in proportion to their energy above reserve, capped at max kW per home; what a capped home can't take goes to the others.
4. **Hold the buffer.** The buffer is sized at fleet level, **`buffer_frac` × promised MW** (default 20%), and held per battery pro rata to each home's call share: a home with share *s* keeps `buffer_frac` × *s* spare, in **power** (its other exports stay ≤ max kW − *s* − buffer) and in **energy** (it keeps reserve + (*s* + buffer) × the rest of the call). It's what failover draws on.
5. **Be call-ready.** Every on-grid home keeps the **next call's energy** above its reserve: its share of the contract × `max_call_ticks` × (1 + `buffer_frac`), capped at its room above the reserve. The share is planned pro rata to room above the reserve (capacity − reserve), not current charge, so a home at its reserve still gets a share. Outside a call, a home below that level **charges up to it whatever the price**, because keeping the promise avoids a penalty at the same price. During a call only the reserve is recovered, since charging then would just net against the fleet's own delivery.
6. **Use headroom**, what's left after 2–5 (during a call, on top of the rest of it). It can run during a call or its cooldown: export if price ≥ $1,000; charge if price ≤ $30; otherwise hold.
7. **Cold snap forecast in the next 24 h?** (below 32°F, behind a flag, default on) Charge to 95% while the price is ≤ $200.

The policy stays behind the existing `Policy` interface. `NaivePolicy` remains as the baseline for comparison.

## Failover
One home's share of the call drops out, so healthy homes raise their output to cover it. The sim ticks every 15 min, so failover runs on a **timeline in seconds inside each tick**.

| | Warned | Silent |
|---|---|---|
| Causes | battery about to hit its floor mid-tick; home whose rolling outage starts next tick (half of them warn, `outage_notice_frac`) | device fault (chaos); the other half of the outages |
| Detection | immediate (the node reports ahead of time) | missed heartbeats: 3 × 2 s (the 2 s interval is ADER's real-time telemetry interval) |
| Time to cover | reassign latency: 5 s | detection + reassign: 11 s |

- **Who drops out** (`backend/failover.py`, only homes with a call share make a failover): a device fault at a random second of the tick; a home whose export would reach its floor, at the second it gets there; a home losing the grid next tick, at a random second. The earliest reason wins.
- **Reassign:** spread the lost share over healthy homes (on grid, not faulted, not dropping out this tick), pro rata to their spare: power = max kW − their export − cover already taken; energy = what's above their floor after their own export, for the rest of the tick. Partial cover is allowed.
- **If nobody can take it**, the rest stays **uncovered** until the end of the tick. The lost kW × uncovered seconds is the shortfall: `delivered_mw` is the tick average, so the penalty and promise kept follow. Its time to cover is reported as "not covered".
- **KPI:** time to cover **< 60 s**. Report **p50 and max** over covered failovers, plus the number uncovered. (p99 ≈ max at our failure counts.)
- **Device faults** (`SilentDeviceFaults`, chaos): 0.005 per home-hour. 80% transient (a comms blip or reboot: back next tick); 20% hard (out for the rest of the replay: no truck rolls in an ice storm). A faulted home can't discharge while out; it still backs up its own house. Once a hard fault is known (missed heartbeats), the policy gives the home no share.

## Weather forecast error
- The controller plans with a **forecast** = actual temperature + error. The error grows with lead time (default ±2°F at 6 h, ±6°F at 48 h) and has a configurable warm bias.
- Households drain according to the **actual** temperature.
- The policy's defence is a safety margin: plan for forecast − k°F.
- Synthetic on purpose. Archived hourly forecasts for Feb 2021 aren't worth chasing today.

## Score (for comparing policies)
Maximise **net revenue** = capacity payment + energy − shortfall penalty − charging cost. Both contracts are hard constraints. **Headroom is reported in MWh, with no $ value.**

## Metrics
| Metric | Where |
|---|---|
| Net revenue (penalty shown as subtext: `incl. −$X penalties`) | counters |
| Promised vs delivered MW, shortfall shaded red | chart |
| Promise kept (% of called intervals) | counters |
| Headroom (MWh, time average) | counters |
| Homes dark: ran out vs by contract; critical homes ran out (must be 0) | counters + map |
| Failovers: warned/silent count, time to cover p50/max, uncovered | counters + failover log |

## Insight experiment
- **Sweep:** contract size 30% → 100% of nameplate × silent-failure rate (low, medium, high) × 3 seeds.
- **Windows compared:** pre-storm (Feb 10–13) vs storm (Feb 14–18). The replay starts Feb 10. Pre-storm prices aren't all normal: Feb 11–12 spike to $4,086 and $2,020 (24 intervals ≥ $1,000), which already triggers calls.
- **Output:** the safe contract size for each window (the largest where promise kept ≥ 99% and no critical home runs out) and what it costs.
- **README:** 2–3 charts generated by a script from the sweep: contract % vs revenue / promise kept; storm vs pre-storm; forecast error vs homes that ran out (stretch).

## Wire changes (one schema commit; regenerate types + fixtures)
- `HomeInfo.tier: none | standard | critical`
- `FleetStats`:
  - `promised_mw` (0 when no call);
  - `utility_call: bool`;
  - `homes_exporting`;
  - `homes_dark_by_contract`;
  - `headroom_mwh`;
  - `penalty_usd` (cumulative);
  - `promise_kept`;
  - `failovers_warned`;
  - `failovers_silent`;
  - `failover_p50_s`;
  - `failover_max_s`;
  - `failovers_uncovered`.
- `TickMessage.failovers: list[{home_id, kind: warned|silent, cover_s | null, covered_by: int}]` for the log.
- `homes_dark` keeps its meaning of "ran out".

## UI changes
- **Chart:** a floating glass panel you can drag, resize, and double-click to expand. Promised and delivered lines with red shortfall shading; price on its own axis.
- **Counters (legend):** On grid · Exporting (blue) · On battery · Dark: ran out · Dark: by contract. They must add up to the fleet size.
- **Top bar:** a "utility call" badge while a call is active.
- **Failover log:** the last few events, e.g. `h0231 silent → covered in 11 s by 3 homes`.

## Cut
- Jev, the confidence gate and the Jev cache. `src` stays `rule`.
- Day-ahead commitments.
- Per-5-minute base points: we judge promises per 15-min interval (a stated simplification).

## Assumptions and sources
| Assumption | Value | Basis |
|---|---|---|
| Utility contract shape | MW capacity, called at peaks, ~1.5 h at full power | Austin Energy × Base 40 MW agreement (APPA) |
| Calls per day | at most 1 per Central-time day (`max_calls_per_day`) | GVEC × Base Power: events "not to exceed one event per day on average" |
| Call window | 06:00–22:00 Central | Austin Energy Power Partner Battery: events between 6am and 10pm |
| Event length | 1.5 h (6 ticks) | ⚠ Austin Energy's programme events run 2–3 h; we keep the shorter Base agreement figure above |
| Events per year | not capped (a 10-day replay at 1/day stays far below it) | Austin Energy: ≤ 40 events a year, **excluding grid emergencies**, which is the `emergency_uncapped` stress case |
| No calls before a storm | off by default (`skip_before_storm`: forecast < 20°F within 24 h) | Austin Energy: typically no events when a severe storm is forecast. ⚠ The 20°F / 24 h threshold is ours |
| Battery floor | never below 20% SoC for export; a backup reserve per home | Austin Energy: never discharged below 20%; GVEC × Base: members keep a minimum backup reserve |
| Call trigger | price threshold | ADER dispatch is limited by bid price vs market price (ERCOT ADER Phase 3 doc) |
| Heartbeat | 2 s; a silent home is declared out after 3 missed | ADER real-time telemetry interval. ⚠ The 3 is ours |
| Reassign latency | 5 s | ⚠ our guess |
| Silent device faults | 0.005 per home-hour (`--fault-rate`) | ⚠ our guess |
| Transient vs hard faults | 80% transient (back next tick), 20% hard (out for the rest of the replay) | ⚠ our guess: comms blips and reboots vs failed hardware nobody can reach in an ice storm |
| Outage notice | half the homes about to lose the grid warn first | ⚠ our guess |
| Per-home reserve | declared per battery | ADER registration asks for each battery's min operating SoC |
| Penalty | shortfall × interval price; repeated misses lead to disqualification | ADER settlement + qualification revocation |
| Max battery power | 12 kW | ⚠ 25 kWh ÷ 1.5 h ≈ 17 kW upper bound; ask Base |
| Capacity payment | $2,000/MW-week | ⚠ placeholder; Base's contract rates aren't public |
| Tiers, backup hours, forecast error | see above | ⚠ configurable guesses |

Sources:
- [Austin Energy × Base Power](https://www.publicpower.org/periodical/article/austin-energy-enters-agreement-with-base-power-deploy-40-mw-residential-battery-storage)
- [GVEC × Base Power](https://www.gvec.org/gvec-x-base-power/)
- [Austin Energy Power Partner Battery](https://austinenergy.com/energy-efficiency/rebates-incentives/residential/appliances-equipment/pp-battery)
- [ERCOT ADER Phase 3 governing document](https://www.ercot.com/files/docs/2025/06/16/4.3-Aggregate-Distributed-Energy-Resource-ADER-Pilot-Project-Phase-3.pdf)
- [ERCOT ADER pilot](https://www.ercot.com/mktrules/pilots/ader)

## Build order (freeze 21:00)
| When | Backend | Frontend |
|---|---|---|
| 15:00–15:30 | schema commit (wire fields above, types, fixtures) | waits on schema; meanwhile the floating chart panel |
| 15:30–17:00 | tiers + forecast reserve + utility call + `ContractPolicy` + revenue/penalty | new counters, exporting swatch, dark by contract, shortfall shading, call badge |
| 17:00–18:30 | failover timeline inside each tick + silent chaos | failover log |
| 18:30–20:00 | sweep script + README charts + the insight number | integrate with live backend |
| 20:00–21:00 | integration, rehearse the replay, fix | polish |

**If late, cut in this order:** step 6 (pre-charge) → forecast error → EEA trigger option → the third seed.
