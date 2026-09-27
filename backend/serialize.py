"""The one place the sim meets the wire (`backend/schema.py`): replay params become a sim,
sim state becomes messages.

Values are validated by the wire models on the way out. Rounding happens here
and only here, for display values that nothing downstream recomputes: SoC, kW
and MW stay exact so the fleet stats keep adding up from the per-home values.
"""

import math

from backend.data import TICK, Frame
from backend.schema import (
    FailoverEvent,
    FleetStats,
    HomeInfo,
    HomeState,
    InitMessage,
    ReplayParams,
    ScenarioParams,
    TickMessage,
)
from backend.sim import Fleet, FleetConfig, Sim, TickResult, uri_replay


def build_sim(params: ScenarioParams, contract: float | None, seed: int = 0, frames: list[Frame] | None = None) -> Sim:
    """A replay of `params.scenario` with a utility contract of `contract` x nameplate (None: no contract)."""
    return uri_replay(
        seed=seed,
        config=FleetConfig(n_homes=params.homes).with_backup_hours("standard", params.standard_backup_h),
        frames=frames,
        policy=params.policy,
        contract_size=contract,
        fault_rate=params.fault_rate,
        policy_options={"headroom_mode": params.headroom_mode} if params.policy == "contract" else None,
        max_calls_per_day=params.max_calls_per_day,
        emergency_uncapped=params.emergency_uncapped,
        skip_before_storm=params.skip_before_storm,
    )


def replay_sim(params: ReplayParams) -> Sim:
    """The replay a /ws connection with these params plays."""
    return build_sim(params, params.contract)


def init_message(sim: Sim, params: ReplayParams) -> InitMessage:
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
        params=params,
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
            contract_pnl_usd=round(r.contract_pnl_usd, 2),
            backup_cost_usd=round(r.backup_cost_usd, 2),
            market_usd=round(r.market_usd, 2),
            revenue_tick_usd=round(r.revenue_tick_usd, 2),
            penalty_usd=round(r.penalty_usd, 2),
            promise_kept=r.promise_kept,
            failovers_warned=r.failovers_warned,
            failovers_silent=r.failovers_silent,
            failovers_uncovered=r.failovers_uncovered,
            failover_p50_s=r.failover_p50_s,
            failover_max_s=r.failover_max_s,
        ),
        failovers=[
            FailoverEvent(
                home_id=fleet.ids[f.home],
                kind="warned" if f.warned else "silent",
                cover_s=f.cover_s,
                covered_by=f.covered_by,
            )
            for f in r.failovers
        ],
    )
