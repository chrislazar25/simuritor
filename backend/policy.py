"""Policy seam: decides every home's action each tick.

A policy sees the whole fleet at once (arrays, one entry per home), so a
model-backed policy can batch its calls. It only proposes: the sim enforces
physics afterwards, so a home without grid power always runs on `backup`
whatever the policy asked for.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from backend.commitment import Commitment
from backend.data import HOURS_PER_TICK, Frame


@dataclass(frozen=True, slots=True)
class FleetView:
    """What a policy may look at this tick. Arrays are read-only, one entry per home."""

    soc: np.ndarray
    """State of charge, 0-1, at the start of the tick."""
    grid: np.ndarray
    """True where the home has grid power this tick."""
    faulted: np.ndarray
    """True where a device fault is known (missed heartbeats): the home can't discharge this tick."""
    capacity_kwh: np.ndarray
    household: np.ndarray
    tier: np.ndarray
    """`Tier` strings: each home's backup contract."""
    reserve_kwh: np.ndarray
    """Homeowner contract: energy kept for backup this tick (tier hours x drain at the forecast temperature)."""
    reserve_floor: float
    """SoC below which the fleet never exports."""
    max_kw: float
    """Max charge/discharge power per home."""
    commitment: Commitment | None
    """What the fleet owes the utility this tick; None when no commitment source is configured."""
    forecast_min_f: Callable[[float], float]
    """Coldest forecast temperature over the next `hours` (this tick included), °F."""
    domain: np.ndarray | None = None
    """Failure domain per home, as the operator knows it: the utility's rotating-outage block (the
    never-restored feeders are one more). None when unknown."""


@dataclass(frozen=True, slots=True)
class Decisions:
    """One entry per home."""

    action: np.ndarray
    """`Action` strings."""
    src: np.ndarray
    """`Source` strings: which tier of the decision stack decided."""
    conf: np.ndarray
    """Confidence 0-1; NaN where the tier has none (rules)."""
    kw: np.ndarray | None = None
    """Target power for `charge`/`discharge`, kW; NaN (or no array) = as much as the sim allows."""
    call_kw: np.ndarray | None = None
    """Each home's share of the utility call, kW, included in `kw`: what failover covers if the
    home drops out. None when the policy doesn't split calls (no failover)."""
    refill_kwh: np.ndarray | None = None
    """Energy each home charges back up to whatever the price for its reserve: charging below it is
    backup cost. None: no such level."""
    call_ready_kwh: np.ndarray | None = None
    """Energy each home charges up to whatever the price to be ready for the next call, at least
    `refill_kwh`: charging between the two is a contract cost. None: no such level."""


class Policy(Protocol):
    def decide(self, frame: Frame, fleet: FleetView) -> Decisions: ...


@dataclass(frozen=True, slots=True)
class NaivePolicy:
    """Price rules (docs/slice-spec.md): sell high, buy low, otherwise hold.

    Plus one recovery rule: a home on grid below the reserve floor charges whatever the
    price, so a home that came back from an outage refills its backup. It only refills to
    the floor; above that, the price rules apply again.
    """

    discharge_at_usd: float = 1000.0
    """Discharge when the price is at least this, $/MWh..."""
    discharge_margin: float = 0.10
    """...and SoC is above reserve floor + this margin."""
    charge_at_usd: float = 30.0
    """Charge when the price is at most this, $/MWh..."""
    charge_below_soc: float = 0.90
    """...and SoC is below this."""

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        discharge = (frame.price >= self.discharge_at_usd) & (
            fleet.soc > fleet.reserve_floor + self.discharge_margin
        )
        recover = fleet.grid & (fleet.soc < fleet.reserve_floor)
        cheap = (frame.price <= self.charge_at_usd) & (fleet.soc < self.charge_below_soc)
        charge = recover | cheap
        action = np.where(discharge, "discharge", np.where(charge, "charge", "hold"))
        n = len(fleet.soc)
        return Decisions(
            action=action,
            src=np.full(n, "rule"),
            conf=np.full(n, np.nan),
            refill_kwh=np.where(fleet.grid, fleet.reserve_floor * fleet.capacity_kwh, 0.0),
        )


@dataclass(frozen=True, slots=True)
class ContractPolicy:
    """Keeps both contracts: a fixed priority list per home (docs/dispatch-design.md, "The policy").

    1. Off grid: backup (the sim enforces it; tier `none` goes dark by contract).
    2. Protect the reserve: never export below the home's floor, its contract reserve or the
       fleet's reserve floor, whichever is higher. A home with a known device fault exports nothing.
    3. Utility call: split the promised MW across on-grid homes pro rata to energy above their
       floor, none above max kW or what it holds this tick (the excess goes to the others).
       `spread_by_domain`: first evenly across the failure domains with such a home, then pro rata
       inside each (`by_domain`).
    4. Buffer: a home with a call share keeps `buffer_frac` x its share spare, in power and in
       energy for the rest of the call. Fleet buffer = `buffer_frac` x promised MW.
       `spread_by_domain`: N-1 instead (`n_minus_1`), the largest domain's share held by the others.
    5. Call-ready: every on-grid home keeps the next call's energy above its floor: its share
       of the contract x `max_call_ticks` x (1 + buffer). The share is planned like a call's (3),
       weighted by room above the floor (capacity - floor), not current charge, so an empty home
       still gets one. Outside a call, a home below that level charges up to it whatever the
       price: keeping the promise avoids a penalty at the same price. The sim books it as a
       contract cost (`Decisions.call_ready_kwh`). (Not during a call, where charging would only
       net against the fleet's own delivery; there only the reserve is recovered.)
    6. Headroom, what's left after 2-5: `headroom_mode` "keep" never exports it; "sell" exports it
       (during a call, on top of the rest of it) if the price is at least `export_at_usd`. Either
       way, charge if the price is at most `charge_at_usd`.
    7. Pre-charge (`precharge`): a cold snap in the forecast and a moderate price: charge to `precharge_soc`.
    """

    headroom_mode: Literal["keep", "sell"] = "keep"
    """`keep`: headroom stays in the batteries (backup, the next call); `sell`: export it at `export_at_usd`."""
    export_at_usd: float = 1000.0
    charge_at_usd: float = 30.0
    precharge: bool = True
    precharge_hours: float = 24.0
    """Look this far ahead for a cold snap..."""
    precharge_below_f: float = 32.0
    """...colder than this, °F..."""
    precharge_max_usd: float = 200.0
    """...and charge while the price is at most this, $/MWh..."""
    precharge_soc: float = 0.95
    """...up to this SoC."""
    spread_by_domain: bool = False
    """Split calls across failure domains (`FleetView.domain`, required then) and hold an N-1
    buffer: rules 3-5. ⚠ Assumes the operator knows the utility's rotation blocks."""

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        n, h = len(fleet.soc), HOURS_PER_TICK
        cap = fleet.capacity_kwh
        energy = fleet.soc * cap
        floor = np.maximum(fleet.reserve_kwh, fleet.reserve_floor * cap)
        can_export = fleet.grid & ~fleet.faulted
        above = np.where(can_export, np.maximum(energy - floor, 0.0), 0.0)

        share = np.zeros(n)
        held_kw = ready_kwh = np.zeros(n)
        c = fleet.commitment
        if c is not None:
            room = np.where(can_export, np.maximum(cap - floor, 0.0), 0.0)
            next_share, next_buffer = self.split(c.contract_mw * 1000, room, np.full(n, fleet.max_kw), fleet, c)
            ready_kwh = np.minimum((1 + next_buffer) * next_share * c.max_call_ticks * h, room)
        held_kwh = ready_kwh
        if c is not None and c.call:
            share, buffer = self.split(c.promised_mw * 1000, above, np.minimum(fleet.max_kw, above / h), fleet, c)
            held_kw = (1 + buffer) * share
            held_kwh = ready_kwh + held_kw * c.ticks_left * h
        headroom_kw = np.clip(np.minimum(fleet.max_kw - held_kw, (above - held_kwh) / h), 0.0, None)
        sell = self.headroom_mode == "sell" and frame.price >= self.export_at_usd
        export_kw = share + (headroom_kw if sell else 0.0)

        # Back up to the reserve, or outside a call to call-ready, whatever the price.
        target = floor if c is not None and c.call else floor + ready_kwh
        charge_kw = np.where(fleet.grid & (energy < target), np.minimum(fleet.max_kw, (target - energy) / h), 0.0)
        if self.precharge and frame.price <= self.precharge_max_usd:
            if fleet.forecast_min_f(self.precharge_hours) < self.precharge_below_f:
                precharge_kw = np.clip((self.precharge_soc * cap - energy) / h, 0.0, fleet.max_kw)
                charge_kw = np.maximum(charge_kw, precharge_kw)
        if frame.price <= self.charge_at_usd:
            charge_kw = np.where(energy < cap, np.nan, charge_kw)  # cheap: fill up

        discharge = export_kw > 0
        charge = ~discharge & fleet.grid & ((charge_kw > 0) | np.isnan(charge_kw))
        action = np.where(
            ~fleet.grid, "backup", np.where(discharge, "discharge", np.where(charge, "charge", "hold"))
        )
        kw = np.where(discharge, export_kw, np.where(charge, charge_kw, 0.0))
        call_kw = np.where(discharge, share, 0.0)
        return Decisions(
            action=action,
            src=np.full(n, "rule"),
            conf=np.full(n, np.nan),
            kw=kw,
            call_kw=call_kw,
            refill_kwh=np.where(fleet.grid, floor, 0.0),
            call_ready_kwh=np.where(fleet.grid, target, 0.0),
        )

    def split(
        self, total_kw: float, weight: np.ndarray, cap: np.ndarray, fleet: FleetView, c: Commitment
    ) -> tuple[np.ndarray, float]:
        """Each home's share of `total_kw` (rule 3) and the buffer to hold on top, as a fraction of it (rule 4)."""
        if not self.spread_by_domain:
            return pro_rata(total_kw, weight, cap), c.buffer_frac
        if fleet.domain is None:
            raise ValueError("spread_by_domain needs each home's failure domain (FleetView.domain)")
        share, per_domain = by_domain(total_kw, weight, cap, fleet.domain)
        return share, n_minus_1(per_domain, fallback=c.buffer_frac)


def by_domain(
    total: float, weight: np.ndarray, cap: np.ndarray, domain: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Split `total` evenly across the domains that have a home with weight, no domain above what
    its homes can take (the excess goes to the others), then `pro_rata` inside each domain.
    Returns the per-home shares and the per-domain totals."""
    _, d = np.unique(domain, return_inverse=True)
    live = np.bincount(d, weights=(weight > 0).astype(float)) > 0
    per_domain = pro_rata(total, weight=live.astype(float), cap=np.bincount(d, weights=np.where(weight > 0, cap, 0.0)))
    share = np.zeros(len(weight))
    for k in np.flatnonzero(per_domain > 0):
        home = d == k
        share[home] = pro_rata(per_domain[k], weight[home], cap[home])
    return share, per_domain


def n_minus_1(per_domain: np.ndarray, fallback: float) -> float:
    """Buffer fraction such that losing the domain with the largest share leaves exactly that
    share spare on the others: largest / (total - largest). 3 even domains: 1/2; 5: 1/4. With
    fewer than two domains no other domain can cover the loss, so `fallback`."""
    if (per_domain > 0).sum() < 2:
        return fallback
    largest = float(per_domain.max())
    return largest / (float(per_domain.sum()) - largest)


def pro_rata(total: float, weight: np.ndarray, cap: np.ndarray) -> np.ndarray:
    """Split `total` in proportion to `weight`, no entry above its `cap`; what a capped entry
    can't take is split among the rest. Sums to less than `total` only when every entry is capped."""
    share = np.zeros(len(weight))
    free = weight > 0
    left = total
    while free.any() and left > 0:
        tentative = left * weight[free] / weight[free].sum()
        over = tentative > cap[free]
        if not over.any():
            share[free] = tentative
            break
        capped = np.flatnonzero(free)[over]
        share[capped] = cap[capped]
        left -= cap[capped].sum()
        free[capped] = False
    return share


POLICIES: dict[str, Callable[[], Policy]] = {"contract": ContractPolicy, "naive": NaivePolicy}
"""Policies selectable by name (run_replay `--policy`, the replay params' `policy`)."""
