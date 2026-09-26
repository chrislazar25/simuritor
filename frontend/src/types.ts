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
   * MW committed ahead of time (e.g. day-ahead); null when no commitment source is configured.
   */
  promised_mw: number | null;
  /**
   * Actual fleet discharge to the grid this tick.
   */
  delivered_mw: number;
  homes_on_grid: number;
  /**
   * Grid down, battery still powering the house.
   */
  homes_on_battery: number;
  /**
   * Grid down and battery empty: lights out.
   */
  homes_dark: number;
  /**
   * Cumulative since replay start; charging at negative prices earns money.
   */
  revenue_usd: number;
  revenue_tick_usd: number;
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
