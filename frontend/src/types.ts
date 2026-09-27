/* Generated from backend/schema.py by `uv run python -m scripts.gen_types`.
 * Do not edit by hand. */

export type Simuritor = WireMessage | SafeContractResponse;
export type WireMessage = ServerMessage | ClientMessage;
export type ServerMessage = InitMessage | TickMessage;
export type ClientMessage = PlayMessage | PauseMessage | SpeedMessage | ResetMessage;

export interface InitMessage {
  type: "init";
  /**
   * Timestamp of tick 0.
   */
  start: string;
  /**
   * Exclusive end of the replay window.
   */
  end: string;
  n_ticks: number;
  params: ReplayParams;
  homes: HomeInfo[];
}
/**
 * The parameters this replay runs with (defaults filled in).
 */
export interface ReplayParams {
  /**
   * `contract`: keeps both contracts (docs/dispatch-design.md); `naive`: the price-rule baseline.
   */
  policy: "contract" | "naive";
  /**
   * Hours of backup the `standard` tier's reserve covers at the forecast temperature.
   */
  standard_backup_h: number;
  /**
   * Utility calls that may start per Central-time day.
   */
  max_calls_per_day: number;
  /**
   * During an EEA a call may start whatever `max_calls_per_day` says (the stress case).
   */
  emergency_uncapped: boolean;
  /**
   * No call while a severe cold snap is in the next 24 h forecast.
   */
  skip_before_storm: boolean;
  /**
   * Silent device faults per home-hour.
   */
  fault_rate: number;
  /**
   * Contract policy only. `keep`: energy above what the contracts need stays in the batteries;
   * `sell`: export it when the price spikes.
   */
  headroom_mode: "keep" | "sell";
  /**
   * Fleet size. 3,000 homes x 12 kW is 36 MW of nameplate, about Base's 40 MW Austin Energy deal.
   */
  homes: number;
  /**
   * Contract policy only. Treat each rotating-outage block as a failure domain (⚠ assumes the
   * operator knows the utility's blocks): split a call evenly across the on-grid domains, then pro
   * rata inside one, and hold an N-1 buffer (losing the largest domain's share leaves that much
   * spare on the others) instead of the fixed 20%.
   */
  spread_by_domain: boolean;
  scenario: "uri" | "normal";
  /**
   * Utility contract size, share of fleet nameplate (homes x max kW).
   */
  contract: number;
}
/**
 * Static facts about one home, sent once in `init`.
 */
export interface HomeInfo {
  id: string;
  lat: number;
  lon: number;
  household: "standard" | "medical" | "elderly" | "wfh";
  /**
   * Backup contract; every `medical` household is `critical`.
   */
  tier: "none" | "standard" | "critical";
  capacity_kwh: number;
}
export interface TickMessage {
  type: "tick";
  i: number;
  /**
   * Interval start, ISO 8601 with UTC offset.
   */
  t: string;
  /**
   * Real-time settlement point price, $/MWh. Can be negative.
   */
  price: number;
  eea: "Normal" | "EEA1" | "EEA2" | "EEA3";
  temp_f: number;
  homes: HomeState[];
  fleet: FleetStats;
  /**
   * Failovers that started or resolved this tick, oldest first.
   */
  failovers: FailoverEvent[];
}
/**
 * Per-tick state of one home. Joined to `HomeInfo` by `id`.
 */
export interface HomeState {
  id: string;
  /**
   * State of charge, 0-1.
   */
  soc: number;
  /**
   * True if the home has grid power this tick.
   */
  grid: boolean;
  action: "charge" | "discharge" | "hold" | "backup";
  /**
   * Battery power magnitude; direction comes from `action`.
   */
  kw: number;
  src: "rule";
  /**
   * Decision confidence, 0-1; null for rule decisions.
   */
  conf: number | null;
}
export interface FleetStats {
  /**
   * What the fleet could physically export this tick: homes on grid, above reserve floor.
   */
  available_mw: number;
  /**
   * MW committed to the utility for this tick: 0 outside calls; null when no commitment source is configured.
   */
  promised_mw: number | null;
  /**
   * Actual fleet discharge to the grid this tick.
   */
  delivered_mw: number;
  /**
   * True while the utility has called on the fleet's contracted capacity.
   */
  utility_call: boolean;
  /**
   * Homes with grid power this tick, including those exporting.
   */
  homes_on_grid: number;
  /**
   * Homes on grid and discharging to it; a subset of `homes_on_grid`.
   */
  homes_exporting: number;
  /**
   * Grid down, battery still powering the house.
   */
  homes_on_battery: number;
  /**
   * Grid down and battery empty: lights out (ran out).
   */
  homes_dark: number;
  /**
   * Grid down, tier `none`: the house is unpowered by contract while the battery keeps its energy.
   */
  homes_dark_by_contract: number;
  /**
   * Fleet energy above each home's contract reserve at the end of the tick.
   *
   * During a call this includes what the rest of the call will draw.
   */
  headroom_mwh: number;
  /**
   * Cumulative net revenue since replay start: `contract_pnl_usd` - `backup_cost_usd` + `market_usd`.
   * Charging at negative prices earns money.
   */
  revenue_usd: number;
  /**
   * Cumulative utility contract P&L: capacity payments + call energy (delivery up to the promise,
   * at the interval price) - shortfall penalties - the cost of charging homes call-ready for the
   * next call outside calls (it exists for the contract).
   */
  contract_pnl_usd: number;
  /**
   * Cumulative cost of charging homes back up to their reserve, whatever the price. Negative if
   * that charging ran at negative prices.
   */
  backup_cost_usd: number;
  /**
   * Cumulative everything else: exports beyond the promise, minus other charging (cheap fills, pre-charge).
   */
  market_usd: number;
  /**
   * Revenue earned this tick alone.
   */
  revenue_tick_usd: number;
  /**
   * Cumulative shortfall penalties since replay start (shortfall x interval price).
   */
  penalty_usd: number;
  /**
   * Share of called intervals where delivery met the promise, 0-1; null until a call has happened.
   */
  promise_kept: number | null;
  /**
   * Cumulative failovers where the home warned before dropping out.
   */
  failovers_warned: number;
  /**
   * Cumulative failovers where the home dropped out without warning (missed heartbeats).
   */
  failovers_silent: number;
  /**
   * Cumulative failovers whose lost output no other home could cover.
   */
  failovers_uncovered: number;
  /**
   * Median seconds to cover a failover so far; null until one has been covered.
   */
  failover_p50_s: number | null;
  /**
   * Slowest cover so far, seconds; null until one has been covered.
   */
  failover_max_s: number | null;
}
/**
 * One home dropping out of an export and the fleet covering for it, for the failover log.
 */
export interface FailoverEvent {
  home_id: string;
  /**
   * `warned`: the home announced it was dropping out; `silent`: detected by missed heartbeats.
   */
  kind: "warned" | "silent";
  /**
   * Seconds from drop-out to full cover; null when not covered this tick.
   */
  cover_s: number | null;
  /**
   * How many homes picked up the lost output.
   */
  covered_by: number;
}
export interface PlayMessage {
  type: "play";
}
export interface PauseMessage {
  type: "pause";
}
export interface SpeedMessage {
  type: "speed";
  ticks_per_sec: number;
}
/**
 * Pause at tick 0 and resend `init`.
 */
export interface ResetMessage {
  type: "reset";
}
/**
 * The largest contract the fleet can promise and keep, in a crisis and in a normal week.
 */
export interface SafeContractResponse {
  params: SweepParams;
  /**
   * Every point is the mean over these replays.
   */
  seeds: number[];
  /**
   * One per scenario: `uri`, then `normal`.
   */
  scenarios: SafeContractCurve[];
}
/**
 * Every replay knob except the scenario and the contract size: GET /api/safe-contract's query
 * (it sweeps the contract size, in every scenario).
 */
export interface SweepParams {
  /**
   * `contract`: keeps both contracts (docs/dispatch-design.md); `naive`: the price-rule baseline.
   */
  policy: "contract" | "naive";
  /**
   * Hours of backup the `standard` tier's reserve covers at the forecast temperature.
   */
  standard_backup_h: number;
  /**
   * Utility calls that may start per Central-time day.
   */
  max_calls_per_day: number;
  /**
   * During an EEA a call may start whatever `max_calls_per_day` says (the stress case).
   */
  emergency_uncapped: boolean;
  /**
   * No call while a severe cold snap is in the next 24 h forecast.
   */
  skip_before_storm: boolean;
  /**
   * Silent device faults per home-hour.
   */
  fault_rate: number;
  /**
   * Contract policy only. `keep`: energy above what the contracts need stays in the batteries;
   * `sell`: export it when the price spikes.
   */
  headroom_mode: "keep" | "sell";
  /**
   * Fleet size. 3,000 homes x 12 kW is 36 MW of nameplate, about Base's 40 MW Austin Energy deal.
   */
  homes: number;
  /**
   * Contract policy only. Treat each rotating-outage block as a failure domain (⚠ assumes the
   * operator knows the utility's blocks): split a call evenly across the on-grid domains, then pro
   * rata inside one, and hold an N-1 buffer (losing the largest domain's share leaves that much
   * spare on the others) instead of the fixed 20%.
   */
  spread_by_domain: boolean;
}
/**
 * Contract size against promise kept and money in one scenario, and the largest safe size.
 */
export interface SafeContractCurve {
  scenario: "uri" | "normal";
  /**
   * Ascending by contract size.
   */
  curve: SafeContractPoint[];
  /**
   * `critical_ran_out` with no utility contract: what the rule compares against.
   */
  baseline_critical_ran_out: number;
  /**
   * The largest contract with `kept` >= 0.95 (or no calls) and no more critical homes running
   * out than with no contract; null if none qualifies.
   */
  safe: number | null;
}
/**
 * One contract size in one scenario, averaged over the seeds.
 */
export interface SafeContractPoint {
  /**
   * Contract size, share of fleet nameplate.
   */
  contract: number;
  /**
   * Share of called intervals kept in the scenario's test window (`uri`: the storm, Feb 14-18;
   * `normal`: the whole week); null if the window had no calls.
   */
  kept: number | null;
  /**
   * `uri` only: the same before the storm (Feb 10-12). Null for `normal`, or with no calls.
   */
  pre_kept: number | null;
  /**
   * Over the whole replay, as in `FleetStats`.
   */
  contract_pnl_usd: number;
  /**
   * Over the whole replay, as in `FleetStats`.
   */
  backup_cost_usd: number;
  /**
   * Failovers no other home could cover, over the whole replay.
   */
  uncovered: number;
  /**
   * Critical-tier homes whose battery ran out during an outage, over the whole replay.
   */
  critical_ran_out: number;
}
