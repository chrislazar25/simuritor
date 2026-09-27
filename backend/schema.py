"""Simuritor wire contract: every message exchanged between backend and frontend.

This module is the single source of truth for the websocket protocol.
`schema/simuritor.schema.json` and `frontend/src/types.ts` are generated from it.

These models describe only what goes over the wire. Sim, policy and chaos code
keep their own internal state and must not import these models; a thin
serializer converts sim state into messages at the edge.

Protocol:
  client -> server   connect to /ws?<ReplayParams as query params> (bad params: closed with a reason)
  server -> client   `init` once on connect and after every reset, then one `tick` per interval
  client -> server   `play` | `pause` | `speed` | `reset`
  GET /api/safe-contract?<SweepParams>  -> `SafeContractResponse`
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

MAX_TICKS_PER_SEC = 64

Action = Literal["charge", "discharge", "hold", "backup"]
"""`backup` = grid is down and the battery powers its own house (no export)."""

Source = Literal["rule", "jev", "fallback"]
"""Which tier of the decision stack produced the action."""

EEA = Literal["Normal", "EEA1", "EEA2", "EEA3"]
"""ERCOT Energy Emergency Alert level."""

Household = Literal["standard", "medical", "elderly", "wfh"]

Tier = Literal["none", "standard", "critical"]
"""Homeowner backup contract: `none` goes dark off grid, `standard` keeps a reserve, `critical` a larger one."""

ScenarioName = Literal["uri", "normal"]
"""`uri`: Winter Storm Uri, Austin, Feb 10-19 2021. `normal`: an ordinary winter week, Feb 21-27 2022."""

Fraction = Annotated[float, Field(ge=0, le=1)]

MAX_HOMES = 10_000


class Wire(BaseModel):
    """Base for every wire model: unknown fields are rejected, instances are immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_attribute_docstrings=True,
        # Fields with defaults (e.g. `type`) stay required in the generated TS types.
        json_schema_serialization_defaults_required=True,
    )


# --- replay parameters (query params) -----------------------------------------


class SweepParams(Wire):
    """Every replay knob except the scenario and the contract size: GET /api/safe-contract's query
    (it sweeps the contract size, in every scenario)."""

    policy: Literal["contract", "naive"] = "contract"
    """`contract`: keeps both contracts (docs/dispatch-design.md); `naive`: the price-rule baseline."""
    standard_backup_h: Annotated[float, Field(ge=0, le=24)] = 8.0
    """Hours of backup the `standard` tier's reserve covers at the forecast temperature."""
    max_calls_per_day: Annotated[int, Field(ge=0, le=10)] = 1
    """Utility calls that may start per Central-time day."""
    emergency_uncapped: bool = False
    """During an EEA a call may start whatever `max_calls_per_day` says (the stress case)."""
    skip_before_storm: bool = False
    """No call while a severe cold snap is in the next 24 h forecast."""
    fault_rate: Annotated[float, Field(ge=0, le=1)] = 0.001
    """Silent device faults per home-hour."""
    headroom_mode: Literal["keep", "sell"] = "keep"
    """Contract policy only. `keep`: energy above what the contracts need stays in the batteries;
    `sell`: export it when the price spikes."""
    homes: Annotated[int, Field(ge=1, le=MAX_HOMES)] = 3000
    """Fleet size. 3,000 homes x 12 kW is 36 MW of nameplate, about Base's 40 MW Austin Energy deal."""
    spread_by_domain: bool = False
    """Contract policy only. Treat each rotating-outage block as a failure domain (⚠ assumes the
    operator knows the utility's blocks): split a call evenly across the on-grid domains, then pro
    rata inside one, and hold an N-1 buffer (losing the largest domain's share leaves that much
    spare on the others) instead of the fixed 20%."""


class ReplayParams(SweepParams):
    """One replay's knobs: the /ws query params, echoed in `init`."""

    scenario: ScenarioName = "uri"
    contract: Fraction = 0.3
    """Utility contract size, share of fleet nameplate (homes x max kW)."""


# --- server -> client ---------------------------------------------------------


class HomeInfo(Wire):
    """Static facts about one home, sent once in `init`."""

    id: str
    lat: float
    lon: float
    household: Household
    tier: Tier
    """Backup contract; every `medical` household is `critical`."""
    capacity_kwh: Annotated[float, Field(gt=0)]


class HomeState(Wire):
    """Per-tick state of one home. Joined to `HomeInfo` by `id`."""

    id: str
    soc: Fraction
    """State of charge, 0-1."""
    grid: bool
    """True if the home has grid power this tick."""
    action: Action
    kw: Annotated[float, Field(ge=0)]
    """Battery power magnitude; direction comes from `action`."""
    src: Source
    conf: Fraction | None
    """Decision confidence, 0-1; null for rule decisions."""


class FleetStats(Wire):
    available_mw: Annotated[float, Field(ge=0)]
    """What the fleet could physically export this tick: homes on grid, above reserve floor."""
    promised_mw: Annotated[float, Field(ge=0)] | None
    """MW committed to the utility for this tick: 0 outside calls; null when no commitment source is configured."""
    delivered_mw: Annotated[float, Field(ge=0)]
    """Actual fleet discharge to the grid this tick."""
    utility_call: bool
    """True while the utility has called on the fleet's contracted capacity."""
    homes_on_grid: Annotated[int, Field(ge=0)]
    """Homes with grid power this tick, including those exporting."""
    homes_exporting: Annotated[int, Field(ge=0)]
    """Homes on grid and discharging to it; a subset of `homes_on_grid`."""
    homes_on_battery: Annotated[int, Field(ge=0)]
    """Grid down, battery still powering the house."""
    homes_dark: Annotated[int, Field(ge=0)]
    """Grid down and battery empty: lights out (ran out)."""
    homes_dark_by_contract: Annotated[int, Field(ge=0)]
    """Grid down, tier `none`: the house is unpowered by contract while the battery keeps its energy."""
    headroom_mwh: Annotated[float, Field(ge=0)]
    """Fleet energy above each home's contract reserve at the end of the tick.

    During a call this includes what the rest of the call will draw."""
    revenue_usd: float
    """Cumulative net revenue since replay start: `contract_pnl_usd` - `backup_cost_usd` + `market_usd`.
    Charging at negative prices earns money."""
    contract_pnl_usd: float
    """Cumulative utility contract P&L: capacity payments + call energy (delivery up to the promise,
    at the interval price) - shortfall penalties - the cost of charging homes call-ready for the
    next call outside calls (it exists for the contract)."""
    backup_cost_usd: float
    """Cumulative cost of charging homes back up to their reserve, whatever the price. Negative if
    that charging ran at negative prices."""
    market_usd: float
    """Cumulative everything else: exports beyond the promise, minus other charging (cheap fills, pre-charge)."""
    revenue_tick_usd: float
    """Revenue earned this tick alone."""
    penalty_usd: Annotated[float, Field(ge=0)]
    """Cumulative shortfall penalties since replay start (shortfall x interval price)."""
    promise_kept: Fraction | None
    """Share of called intervals where delivery met the promise, 0-1; null until a call has happened."""
    failovers_warned: Annotated[int, Field(ge=0)]
    """Cumulative failovers where the home warned before dropping out."""
    failovers_silent: Annotated[int, Field(ge=0)]
    """Cumulative failovers where the home dropped out without warning (missed heartbeats)."""
    failovers_uncovered: Annotated[int, Field(ge=0)]
    """Cumulative failovers whose lost output no other home could cover."""
    failover_p50_s: Annotated[float, Field(ge=0)] | None
    """Median seconds to cover a failover so far; null until one has been covered."""
    failover_max_s: Annotated[float, Field(ge=0)] | None
    """Slowest cover so far, seconds; null until one has been covered."""


class FailoverEvent(Wire):
    """One home dropping out of an export and the fleet covering for it, for the failover log."""

    home_id: str
    kind: Literal["warned", "silent"]
    """`warned`: the home announced it was dropping out; `silent`: detected by missed heartbeats."""
    cover_s: Annotated[float, Field(ge=0)] | None
    """Seconds from drop-out to full cover; null when not covered this tick."""
    covered_by: Annotated[int, Field(ge=0)]
    """How many homes picked up the lost output."""


class InitMessage(Wire):
    type: Literal["init"] = "init"
    start: AwareDatetime
    """Timestamp of tick 0."""
    end: AwareDatetime
    """Exclusive end of the replay window."""
    n_ticks: Annotated[int, Field(gt=0)]
    params: ReplayParams
    """The parameters this replay runs with (defaults filled in)."""
    homes: list[HomeInfo]


class TickMessage(Wire):
    type: Literal["tick"] = "tick"
    i: Annotated[int, Field(ge=0)]
    t: AwareDatetime
    """Interval start, ISO 8601 with UTC offset."""
    price: float
    """Real-time settlement point price, $/MWh. Can be negative."""
    eea: EEA
    temp_f: float
    homes: list[HomeState]
    fleet: FleetStats
    failovers: list[FailoverEvent]
    """Failovers that started or resolved this tick, oldest first."""


ServerMessage = Annotated[InitMessage | TickMessage, Field(discriminator="type")]


# --- GET /api/safe-contract ---------------------------------------------------


class SafeContractPoint(Wire):
    """One contract size in one scenario, averaged over the seeds."""

    contract: Fraction
    """Contract size, share of fleet nameplate."""
    kept: Fraction | None
    """Share of called intervals kept in the scenario's test window (`uri`: the storm, Feb 14-18;
    `normal`: the whole week); null if the window had no calls."""
    pre_kept: Fraction | None
    """`uri` only: the same before the storm (Feb 10-12). Null for `normal`, or with no calls."""
    contract_pnl_usd: float
    """Over the whole replay, as in `FleetStats`."""
    backup_cost_usd: float
    """Over the whole replay, as in `FleetStats`."""
    uncovered: Annotated[float, Field(ge=0)]
    """Failovers no other home could cover, over the whole replay."""
    critical_ran_out: Annotated[float, Field(ge=0)]
    """Critical-tier homes whose battery ran out during an outage, over the whole replay."""


class SafeContractCurve(Wire):
    """Contract size against promise kept and money in one scenario, and the largest safe size."""

    scenario: ScenarioName
    curve: list[SafeContractPoint]
    """Ascending by contract size."""
    baseline_critical_ran_out: Annotated[float, Field(ge=0)]
    """`critical_ran_out` with no utility contract: what the rule compares against."""
    safe: Fraction | None
    """The largest contract with `kept` >= 0.95 (or no calls) and no more critical homes running
    out than with no contract; null if none qualifies."""


class SafeContractResponse(Wire):
    """The largest contract the fleet can promise and keep, in a crisis and in a normal week."""

    params: SweepParams
    seeds: list[int]
    """Every point is the mean over these replays."""
    scenarios: list[SafeContractCurve]
    """One per scenario: `uri`, then `normal`."""


# --- client -> server ---------------------------------------------------------


class PlayMessage(Wire):
    type: Literal["play"] = "play"


class PauseMessage(Wire):
    type: Literal["pause"] = "pause"


class SpeedMessage(Wire):
    type: Literal["speed"] = "speed"
    ticks_per_sec: Annotated[float, Field(gt=0, le=MAX_TICKS_PER_SEC)]


class ResetMessage(Wire):
    """Pause at tick 0 and resend `init`."""

    type: Literal["reset"] = "reset"


ClientMessage = Annotated[
    PlayMessage | PauseMessage | SpeedMessage | ResetMessage,
    Field(discriminator="type"),
]


server_message = TypeAdapter(ServerMessage)
client_message = TypeAdapter(ClientMessage)
