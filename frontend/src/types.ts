/* Generated from backend/schema.py by `uv run python -m scripts.gen_types`.
 * Do not edit by hand. */

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
  homes: HomeInfo[];
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
  src: "rule" | "jev" | "fallback";
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
   * Cumulative since replay start; charging at negative prices earns money.
   */
  revenue_usd: number;
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
