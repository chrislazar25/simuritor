"""UtilityContract: when the utility calls, for how long, and what it pays."""

from datetime import datetime

import pytest

from backend.commitment import UtilityContract
from backend.data import TICK, TZ, Frame
from backend.schema import EEA


def ct(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2021, 2, day, hour, minute, tzinfo=TZ)


def commit_all(contract: UtilityContract, ticks: list[tuple[datetime, float, EEA]], forecast_f: float = 50.0) -> str:
    """One character per (time, price, EEA) tick: `C` called, `.` not."""
    return "".join(
        "C" if contract.commit(Frame(i=k, t=t, price=p, temp_f=20.0, eea=e), lambda hours: forecast_f).call else "."
        for k, (t, p, e) in enumerate(ticks)
    )


def calls(
    prices: list[float],
    start: datetime = ct(15, 12),
    eea: list[EEA] | None = None,
    forecast_f: float = 50.0,
    **options,
) -> str:
    """Consecutive ticks from `start` (noon by default: inside the call window)."""
    ticks = [(start + k * TICK, p, e) for k, (p, e) in enumerate(zip(prices, eea or ["Normal"] * len(prices)))]
    return commit_all(UtilityContract(nameplate_mw=6.0, **options), ticks, forecast_f)


def test_call_is_capped_at_6_ticks_then_8_ticks_of_cooldown() -> None:
    assert calls([9000] * 30, max_calls_per_day=10) == "CCCCCC........CCCCCC........CC"


def test_call_starts_at_the_trigger_and_ends_with_the_price() -> None:
    assert calls([999, 1000, 1000, 999]) == ".CC."


def test_cooldown_follows_a_call_that_ended_early() -> None:
    """8 ticks without a call after the last called tick, however it ended."""
    assert calls([9000, 500] + [9000] * 9, max_calls_per_day=10) == "C........CC"


def test_one_call_per_day_by_default() -> None:
    assert calls([9000] * 30) == "CCCCCC" + "." * 24
    assert calls([9000] * 30, max_calls_per_day=2) == "CCCCCC........CCCCCC" + "." * 10


def test_the_daily_limit_resets_at_midnight_central() -> None:
    """Feb 15's call is used up in the evening; Feb 16 gets its own from 06:00."""
    ticks = [(t, 9000.0, "Normal") for t in (ct(15, 21, 30), ct(15, 21, 45), ct(16, 5, 45), ct(16, 6), ct(16, 6, 15))]
    assert commit_all(UtilityContract(nameplate_mw=6.0, cooldown_ticks=0), ticks) == "CC.CC"


def test_calls_only_between_6_and_22_central() -> None:
    assert calls([9000] * 4, start=ct(15, 5, 30)) == "..CC"
    assert calls([9000] * 4, start=ct(15, 21, 30)) == "CC.."  # a call still running at 22:00 ends


@pytest.mark.parametrize(
    ("skip", "forecast_f", "called"),
    [
        (True, 19.9, False),  # below 20 °F in the next 24 h: keep the batteries for backup
        (True, 20.0, True),
        (False, 5.0, True),  # off by default
    ],
)
def test_skip_before_storm(skip: bool, forecast_f: float, called: bool) -> None:
    assert calls([9000], forecast_f=forecast_f, skip_before_storm=skip) == ("C" if called else ".")


def test_emergency_uncapped_ignores_the_daily_limit_during_an_eea() -> None:
    eea3: list[EEA] = ["EEA3"] * 30
    assert calls([9000] * 30, eea=eea3) == "CCCCCC" + "." * 24  # off by default: capped
    assert calls([9000] * 30, eea=eea3, emergency_uncapped=True) == "CCCCCC........CCCCCC........CC"


def test_emergency_calls_dont_count_against_the_daily_limit() -> None:
    """An EEA call, then the day's one normal call, then nothing: the limit applies again."""
    eea: list[EEA] = ["EEA3"] * 14 + ["Normal"] * 16
    assert calls([9000] * 30, eea=eea, emergency_uncapped=True) == "CCCCCC........CCCCCC.........."


def test_commitment_during_a_call() -> None:
    contract = UtilityContract(nameplate_mw=6.0)
    frames = [Frame(i=k, t=ct(15, 12) + k * TICK, price=9000, temp_f=20.0, eea="Normal") for k in range(7)]
    owed = [contract.commit(f, lambda hours: 50.0) for f in frames]
    assert [c.promised_mw for c in owed] == pytest.approx([3.6] * 6 + [0.0])  # 60% of 6 MW, then cooldown
    assert [c.ticks_left for c in owed] == [6, 5, 4, 3, 2, 1, 0]
    assert all(c.buffer_frac == 0.2 and c.contract_mw == pytest.approx(3.6) and c.max_call_ticks == 6 for c in owed)


def test_capacity_payment_every_tick_called_or_not() -> None:
    """$2,000/MW-week x 3.6 MW = $7,200 a week = 672 ticks; also outside the window and at low prices."""
    contract = UtilityContract(nameplate_mw=6.0)
    for k, (t, price) in enumerate([(ct(15, 12), 9000), (ct(15, 12, 15), 20), (ct(16, 3), 9000)]):
        frame = Frame(i=k, t=t, price=price, temp_f=20.0, eea="Normal")
        assert contract.commit(frame, lambda hours: 50.0).capacity_usd == pytest.approx(7200 / 672)
