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
- Paid two ways:
  - a **capacity payment** ($/MW-week, whether or not it's called; default $2,000/MW-week ≈ $100/kW-yr, in the range of a peaker's cost of new entry);
  - energy delivered during a call, paid at the interval price.
- **Shortfall** (delivered < promised) is charged at the interval price. That's the penalty. Missed intervals are also counted, because repeated misses are what get an aggregator's qualification revoked.

## The policy: a fixed priority list, per home, per 15-min tick
1. **Off grid?** Tiers `standard`/`critical` power the house from the battery. Tier `none` goes dark and keeps its energy.
2. **Protect the reserve** (tier × forecast temperature).
3. **Utility call active?** Deliver the contracted MW. Split it across on-grid homes in proportion to their energy above reserve.
4. **Hold the buffer.** Buffer = nameplate − contract. It's what failover draws on.
5. **Use headroom** (can run during a call too): export if price ≥ $1,000 and there's energy above reserve + share of call + buffer; charge if price ≤ $30; otherwise hold.
6. **Cold snap forecast in the next 24 h?** Charge up beforehand, while prices are still low.

The policy stays behind the existing `Policy` interface. `NaivePolicy` remains as the baseline for comparison.

## Failover
One home's share of the call drops out, so healthy homes raise their output to cover it. The sim ticks every 15 min, so failover runs on a **timeline in seconds inside each tick**.

| | Warned | Silent |
|---|---|---|
| Causes | battery close to its reserve; home about to lose grid (rolling outage) | inverter fault, lost telemetry (chaos injection) |
| Detection | immediate (the node reports ahead of time) | missed heartbeats: 3 × 2 s (the 2 s interval is ADER's real-time telemetry interval) |
| Time to cover | ≈ 0 s | detection + reassign latency (default 5 s) |

- **Reassign:** spread the lost kW over healthy on-grid homes that have both power headroom (below max kW) and energy headroom (above reserve).
- **If nobody can take it**, the failure stays **uncovered** until the next tick. It counts as a shortfall, and its time to cover is reported as "not covered".
- **KPI:** time to cover **< 60 s**. Report **p50 and max**, plus the number uncovered. (p99 ≈ max at our failure counts.)
- Most failures during Uri come from the replay itself (rolling outages and batteries hitting their reserve). Chaos only adds the silent ones, at a configurable rate.

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
- **Windows compared:** pre-storm (Feb 10–13) vs storm (Feb 14–18). Verify pre-storm prices are actually normal before relying on it.
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
| Call trigger | price threshold | ADER dispatch is limited by bid price vs market price (ERCOT ADER Phase 3 doc) |
| Heartbeat | 2 s | ADER real-time telemetry interval |
| Per-home reserve | declared per battery | ADER registration asks for each battery's min operating SoC |
| Penalty | shortfall × interval price; repeated misses lead to disqualification | ADER settlement + qualification revocation |
| Max battery power | 12 kW | ⚠ 25 kWh ÷ 1.5 h ≈ 17 kW upper bound; ask Base |
| Capacity payment | $2,000/MW-week | ⚠ placeholder; Base's contract rates aren't public |
| Tiers, backup hours, failure rates, forecast error, reassign latency | see above | ⚠ configurable guesses |

Sources:
- [Austin Energy × Base Power](https://www.publicpower.org/periodical/article/austin-energy-enters-agreement-with-base-power-deploy-40-mw-residential-battery-storage)
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
