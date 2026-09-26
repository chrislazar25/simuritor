"""NaivePolicy: the spec's price rules."""

from datetime import datetime

import numpy as np
import pytest

from backend.data import TZ, Frame
from backend.policy import FleetView, NaivePolicy


def decide(price: float, soc: float, grid: bool = True) -> str:
    frame = Frame(i=0, t=datetime(2021, 2, 15, tzinfo=TZ), price=price, temp_f=20.0, eea="Normal")
    view = FleetView(
        soc=np.array([soc]),
        grid=np.array([grid]),
        capacity_kwh=np.array([25.0]),
        household=np.array(["standard"]),
        reserve_floor=0.20,
    )
    decisions = NaivePolicy().decide(frame, view)
    assert decisions.src[0] == "rule" and np.isnan(decisions.conf[0])
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
    assert decide(price, soc) == action


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
    assert decide(price, soc, grid) == action
