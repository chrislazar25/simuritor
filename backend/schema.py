"""Simuritor wire contract: every message exchanged between backend and frontend.

This module is the single source of truth for the websocket protocol.
`schema/simuritor.schema.json` and `frontend/src/types.ts` are generated from it.

These models describe only what goes over the wire. Sim, policy and chaos code
keep their own internal state and must not import these models; a thin
serializer converts sim state into messages at the edge.

Protocol:
  server -> client   `init` once on connect and after every reset, then one `tick` per interval
  client -> server   `play` | `pause` | `speed` | `reset`
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

Fraction = Annotated[float, Field(ge=0, le=1)]


class Wire(BaseModel):
    """Base for every wire model: unknown fields are rejected, instances are immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_attribute_docstrings=True,
        # Fields with defaults (e.g. `type`) stay required in the generated TS types.
        json_schema_serialization_defaults_required=True,
    )


# --- server -> client ---------------------------------------------------------


class HomeInfo(Wire):
    """Static facts about one home, sent once in `init`."""

    id: str
    lat: float
    lon: float
    household: Household
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
    """MW committed ahead of time (e.g. day-ahead); null when no commitment source is configured."""
    delivered_mw: Annotated[float, Field(ge=0)]
    """Actual fleet discharge to the grid this tick."""
    homes_on_grid: Annotated[int, Field(ge=0)]
    homes_on_battery: Annotated[int, Field(ge=0)]
    """Grid down, battery still powering the house."""
    homes_dark: Annotated[int, Field(ge=0)]
    """Grid down and battery empty: lights out."""
    revenue_usd: float
    """Cumulative since replay start; charging at negative prices earns money."""
    revenue_tick_usd: float


class InitMessage(Wire):
    type: Literal["init"] = "init"
    start: AwareDatetime
    """Timestamp of tick 0."""
    end: AwareDatetime
    """Exclusive end of the replay window."""
    n_ticks: Annotated[int, Field(gt=0)]
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


ServerMessage = Annotated[InitMessage | TickMessage, Field(discriminator="type")]


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
