"""Policies: NaivePolicy's price rules, and ContractPolicy keeping both contracts."""

from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest

from backend.commitment import Commitment
from backend.data import TZ, Frame
from backend.policy import ContractPolicy, Decisions, FleetView, NaivePolicy, Policy, pro_rata


def frame(price: float) -> Frame:
    return Frame(i=0, t=datetime(2021, 2, 15, tzinfo=TZ), price=price, temp_f=20.0, eea="Normal")


def view(
    soc: list[float],
    grid: list[bool] | None = None,
    reserve_kwh: list[float] | None = None,
    promised_mw: float | None = None,
    ticks_left: int = 1,
    contract_mw: float | None = None,
    forecast_f: float = 50.0,
) -> FleetView:
    """40 kWh homes, 12 kW max, a 5% reserve floor so the contract reserve is what binds.

    `promised_mw` set: a utility call with a 20% buffer. `contract_mw`: what the next call (6 ticks)
    asks for; defaults to the promise, or 0 outside a call. `forecast_f`: the coldest forecast, any horizon.
    """
    n = len(soc)
    call = promised_mw is not None
    if contract_mw is None:
        contract_mw = promised_mw or 0.0
    return FleetView(
        soc=np.array(soc),
        grid=np.array(grid or [True] * n),
        capacity_kwh=np.full(n, 40.0),
        household=np.full(n, "standard"),
        tier=np.full(n, "standard"),
        reserve_kwh=np.array(reserve_kwh or [0.0] * n),
        reserve_floor=0.05,
        max_kw=12.0,
        commitment=Commitment(
            call=call,
            promised_mw=promised_mw or 0.0,
            ticks_left=ticks_left if call else 0,
            contract_mw=contract_mw,
            max_call_ticks=6,
            buffer_frac=0.2,
            capacity_usd=0.0,
        ),
        forecast_min_f=lambda hours: forecast_f,
    )


def decide(policy: Policy, price: float, fleet: FleetView) -> Decisions:
    decisions = policy.decide(frame(price), fleet)
    assert (decisions.src == "rule").all() and np.isnan(decisions.conf).all()
    return decisions


# --- NaivePolicy ---------------------------------------------------------------


def naive(price: float, soc: float, grid: bool = True) -> str:
    decisions = decide(NaivePolicy(), price, replace(view([soc], grid=[grid]), reserve_floor=0.20))
    assert decisions.kw is None  # as much as the sim allows
    return str(decisions.action[0])


@pytest.mark.parametrize(
    ("price", "soc", "action"),
    [
        (1000, 0.31, "discharge"),  # at the price threshold, above floor + 10%
        (9000, 0.30, "hold"),  # not above floor + 10%
        (999.99, 0.95, "hold"),
        (30, 0.89, "charge"),  # at the price threshold, below 90%
        (-20, 0.50, "charge"),  # negative prices: charging earns money
        (30, 0.90, "hold"),  # not below 90%
        (30.01, 0.50, "hold"),
    ],
)
def test_naive_rules(price: float, soc: float, action: str) -> None:
    assert naive(price, soc) == action


@pytest.mark.parametrize(
    ("price", "soc", "grid", "action"),
    [
        (9000, 0.19, True, "charge"),  # back on grid below the floor: refill whatever the price
        (9000, 0.00, True, "charge"),
        (9000, 0.20, True, "hold"),  # at the floor: price rules again
        (9000, 0.10, False, "hold"),  # no grid, nothing to charge from (the sim makes it backup)
    ],
)
def test_recovery_rule(price: float, soc: float, grid: bool, action: str) -> None:
    assert naive(price, soc, grid) == action


# --- ContractPolicy ------------------------------------------------------------


def contract(price: float, fleet: FleetView, **kwargs) -> tuple[list[str], list[float]]:
    decisions = decide(ContractPolicy(**kwargs), price, fleet)
    assert decisions.kw is not None
    return decisions.action.tolist(), decisions.kw.tolist()


def test_pro_rata_splits_by_weight_and_passes_the_excess_on() -> None:
    assert pro_rata(30.0, np.array([20.0, 10.0, 10.0]), np.full(3, 100.0)).tolist() == [15.0, 7.5, 7.5]
    # Home 0 is capped at 12; the 3 kW it can't take is split between the others.
    assert pro_rata(30.0, np.array([20.0, 10.0, 10.0]), np.full(3, 12.0)).tolist() == [12.0, 9.0, 9.0]
    assert pro_rata(30.0, np.array([20.0, 0.0]), np.full(2, 12.0)).tolist() == [12.0, 0.0]  # short: all capped


def test_call_split_is_pro_rata_to_energy_above_reserve() -> None:
    """Energy above reserve 12, 6, 0 kWh, and home 3 is off grid: 12 kW promised splits 8 / 4 / 0 / 0."""
    fleet = view([0.5, 0.5, 0.5, 0.9], grid=[True, True, True, False], reserve_kwh=[8, 14, 20, 0], promised_mw=0.012)
    action, kw = contract(price=500, fleet=fleet)  # below the export price: only the call
    assert action == ["discharge", "discharge", "hold", "backup"]
    assert kw == pytest.approx([8.0, 4.0, 0.0, 0.0])


def test_call_share_is_capped_at_max_kw_and_the_rest_moves_on() -> None:
    fleet = view([0.9, 0.5], reserve_kwh=[0, 10], promised_mw=0.02)  # 34 (above the 5% floor) and 10 kWh
    _, kw = contract(price=500, fleet=fleet)
    assert kw == pytest.approx([12.0, 8.0])


def test_buffer_is_held_in_power() -> None:
    """Share 5 kW + buffer 1 kW: headroom export may use only 12 - 6 = 6 kW more."""
    fleet = view([0.9], promised_mw=0.005)
    _, kw = contract(price=1000, fleet=fleet)
    assert kw == pytest.approx([5.0 + 6.0])


def test_buffer_is_held_in_energy_for_this_call_and_the_next() -> None:
    """10 kWh above reserve, a 4 kW share: (4 + 0.8) kW x 0.25 h = 1.2 kWh held per call tick.

    Last tick of the call: 1 + 6 (the next call) ticks = 8.4 kWh held. That leaves 1.6 kWh, i.e.
    6.4 kW this tick (power would allow 12 - 4.8 = 7.2): 4 + 6.4. With 2 ticks left, 8 ticks =
    9.6 kWh is held: 0.4 kWh = 1.6 kW of headroom export.
    """
    fleet = view([0.5], reserve_kwh=[10], promised_mw=0.004, ticks_left=1)
    assert contract(price=1000, fleet=fleet)[1] == pytest.approx([4.0 + 6.4])
    fleet = view([0.5], reserve_kwh=[10], promised_mw=0.004, ticks_left=2)
    assert contract(price=1000, fleet=fleet)[1] == pytest.approx([4.0 + 1.6])


def test_outside_a_call_headroom_keeps_the_next_calls_energy() -> None:
    """No call (a cooldown, say), 10 kWh above reserve. A 4 kW contract: the next call needs
    4 x 1.2 x 1.5 h = 7.2 kWh, so 2.8 kWh (11.2 kW) is sellable. An 8 kW contract needs 14.4: hold.
    """
    action, kw = contract(price=1000, fleet=view([0.5], reserve_kwh=[10], contract_mw=0.004))
    assert action == ["discharge"] and kw == pytest.approx([11.2])
    action, kw = contract(price=1000, fleet=view([0.5], reserve_kwh=[10], contract_mw=0.008))
    assert action == ["hold"] and kw == [0.0]


def test_the_next_calls_energy_is_split_pro_rata() -> None:
    """20 and 10 kWh above reserve, a 12 kW contract: next-call shares 8 and 4 kW, kept for 1.5 h
    with the buffer: 14.4 and 7.2 kWh. Sellable: 5.6 and 2.8 kWh, capped at 12 kW."""
    _, kw = contract(price=1000, fleet=view([0.55, 0.5], reserve_kwh=[2, 10], contract_mw=0.012))
    assert kw == pytest.approx([12.0, 11.2])


def test_fleet_buffer_is_buffer_frac_of_the_promise() -> None:
    fleet = view([0.5, 0.7, 0.9], promised_mw=0.02)
    _, kw = contract(price=1000, fleet=fleet)
    spare = [12.0 - k for k in kw]
    assert sum(spare) == pytest.approx(0.2 * 20.0)


def test_headroom_export_never_touches_the_reserve() -> None:
    """No call. Home 0 has 2 kWh above reserve (8 kW this tick); home 1 is at its reserve."""
    action, kw = contract(price=1000, fleet=view([0.5, 0.5], reserve_kwh=[18, 20]))
    assert action == ["discharge", "hold"] and kw == pytest.approx([8.0, 0.0])
    action, _ = contract(price=999, fleet=view([0.5, 0.5], reserve_kwh=[18, 20]))
    assert action == ["hold", "hold"]


def test_reserve_floor_binds_when_higher_than_the_contract_reserve() -> None:
    fleet = view([0.10])  # 4 kWh, the 5% floor is 2 kWh: 2 kWh above it
    assert contract(price=1000, fleet=fleet)[1] == pytest.approx([8.0])


def test_recover_charges_back_to_the_reserve_whatever_the_price() -> None:
    """Home 0 on grid 1 kWh below its reserve: 4 kW. Home 1 is off grid: nothing to charge from."""
    action, kw = contract(price=9000, fleet=view([0.5, 0.5], grid=[True, False], reserve_kwh=[21, 21]))
    assert action == ["charge", "backup"] and kw == pytest.approx([4.0, 0.0])


def test_cheap_power_fills_up() -> None:
    action, kw = contract(price=30, fleet=view([0.5, 1.0]))
    assert action == ["charge", "hold"] and np.isnan(kw[0])  # as much as the sim allows


@pytest.mark.parametrize(
    ("price", "forecast_f", "precharge", "action"),
    [
        (200, 31.9, True, "charge"),
        (200.01, 31.9, True, "hold"),  # too expensive
        (200, 32.0, True, "hold"),  # no cold snap
        (200, 31.9, False, "hold"),  # step 6 off
    ],
)
def test_precharge_before_a_cold_snap(price: float, forecast_f: float, precharge: bool, action: str) -> None:
    got, kw = contract(price, view([0.5], forecast_f=forecast_f), precharge=precharge)
    assert got == [action]
    if action == "charge":
        assert kw == pytest.approx([12.0])


def test_precharge_stops_at_95_percent() -> None:
    _, kw = contract(price=100, fleet=view([0.94], forecast_f=10.0))
    assert kw == pytest.approx([0.4 / 0.25])  # 0.4 kWh to 95%
