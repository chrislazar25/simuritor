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
        HomeInfo(id=id_, lat=round(lat, 5), lon=round(lon, 5), household=household, capacity_kwh=capacity)
        for id_, lat, lon, household, capacity in zip(
            fleet.ids,
            fleet.lat.tolist(),
            fleet.lon.tolist(),
            fleet.household.tolist(),
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
            homes_on_grid=r.homes_on_grid,
            homes_on_battery=r.homes_on_battery,
            homes_dark=r.homes_dark,
            revenue_usd=round(r.revenue_usd, 2),
            revenue_tick_usd=round(r.revenue_tick_usd, 2),
        ),
    )
