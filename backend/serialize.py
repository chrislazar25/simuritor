"""The one place sim state becomes wire messages (`backend/schema.py`).

Values are validated by the wire models on the way out. Rounding happens here
and only here, for display values that nothing downstream recomputes: SoC, kW
and MW stay exact so the fleet stats keep adding up from the per-home values.
"""

import math

from backend.data import TICK
from backend.schema import FleetStats, HomeInfo, HomeState, InitMessage, TickMessage
from backend.sim import Fleet, Sim, TickResult


def init_message(sim: Sim) -> InitMessage:
    fleet = sim.fleet
    homes = [
        HomeInfo(
            id=id_, lat=round(lat, 5), lon=round(lon, 5), household=household, tier=tier, capacity_kwh=capacity
        )
        for id_, lat, lon, household, tier, capacity in zip(
            fleet.ids,
            fleet.lat.tolist(),
            fleet.lon.tolist(),
            fleet.household.tolist(),
            fleet.tier.tolist(),
            fleet.capacity_kwh.tolist(),
            strict=True,
        )
    ]
    return InitMessage(
        start=sim.frames[0].t,
        end=sim.frames[-1].t + TICK,
        n_ticks=len(sim.frames),
        homes=homes,
    )


def tick_message(fleet: Fleet, r: TickResult) -> TickMessage:
    homes = [
        HomeState(id=id_, soc=soc, grid=grid, action=action, kw=kw, src=src, conf=None if math.isnan(conf) else conf)
        for id_, soc, grid, action, kw, src, conf in zip(
            fleet.ids,
            r.soc.tolist(),
            r.grid.tolist(),
            r.action.tolist(),
            r.kw.tolist(),
            r.src.tolist(),
            r.conf.tolist(),
            strict=True,
        )
    ]
    return TickMessage(
        i=r.frame.i,
        t=r.frame.t,
        price=r.frame.price,
        eea=r.frame.eea,
        temp_f=round(r.frame.temp_f, 1),
        homes=homes,
        fleet=FleetStats(
            available_mw=r.available_mw,
            promised_mw=r.promised_mw,
            delivered_mw=r.delivered_mw,
            utility_call=r.utility_call,
            homes_on_grid=r.homes_on_grid,
            homes_exporting=int((r.grid & (r.action == "discharge")).sum()),
            homes_on_battery=r.homes_on_battery,
            homes_dark=r.homes_dark,
            homes_dark_by_contract=r.homes_dark_by_contract,
            headroom_mwh=r.headroom_mwh,
            revenue_usd=round(r.revenue_usd, 2),
            revenue_tick_usd=round(r.revenue_tick_usd, 2),
            penalty_usd=round(r.penalty_usd, 2),
            promise_kept=r.promise_kept,
            failovers_warned=0,  # filled by failover
            failovers_silent=0,  # filled by failover
            failovers_uncovered=0,  # filled by failover
            failover_p50_s=None,  # filled by failover
            failover_max_s=None,  # filled by failover
        ),
        failovers=[],  # filled by failover
    )
