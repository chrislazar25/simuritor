"""UtilityContract: when the utility calls, for how long, and what it pays."""

from datetime import datetime

import pytest

from backend.commitment import UtilityContract
from backend.data import TZ, Frame


def at(price: float) -> Frame:
    return Frame(i=0, t=datetime(2021, 2, 15, tzinfo=TZ), price=price, temp_f=20.0, eea="Normal")


def calls(prices: list[float]) -> str:
    """One character per tick: `C` called, `.` not."""
    contract = UtilityContract(nameplate_mw=6.0)
    return "".join("C" if contract.commit(at(p)).call else "." for p in prices)


def test_call_is_capped_at_6_ticks_then_8_ticks_of_cooldown() -> None:
    assert calls([9000] * 30) == "CCCCCC........CCCCCC........CC"


def test_call_starts_at_the_trigger_and_ends_with_the_price() -> None:
    assert calls([999, 1000, 1000, 999]) == ".CC."


def test_cooldown_follows_a_call_that_ended_early() -> None:
    """8 ticks without a call after the last called tick, however it ended."""
    assert calls([9000, 500] + [9000] * 9) == "C........CC"


def test_commitment_during_a_call() -> None:
    contract = UtilityContract(nameplate_mw=6.0)
    owed = [contract.commit(at(9000)) for _ in range(7)]
    assert [c.promised_mw for c in owed] == pytest.approx([3.6] * 6 + [0.0])  # 60% of 6 MW, then cooldown
    assert [c.ticks_left for c in owed] == [6, 5, 4, 3, 2, 1, 0]
    assert all(c.buffer_frac == 0.2 and c.contract_mw == pytest.approx(3.6) and c.max_call_ticks == 6 for c in owed)


def test_capacity_payment_every_tick_called_or_not() -> None:
    """$2,000/MW-week x 3.6 MW = $7,200 a week = 672 ticks."""
    contract = UtilityContract(nameplate_mw=6.0)
    for price in (9000, 20):
        assert contract.commit(at(price)).capacity_usd == pytest.approx(7200 / 672)
