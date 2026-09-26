"""The Uri data source: EEA timeline, frames from the parquet files, and loud failures."""

import math
import shutil
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pandas as pd
import pytest

from backend.data import DATA_DIR, EEA_TIMELINE, TICK, TZ, Frame, UriParquetSource, eea_at


def ct(month_day: str, hh_mm: str = "00:00") -> datetime:
    """A Feb 2021 Central time, e.g. ct("15", "02:00")."""
    return datetime.fromisoformat(f"2021-02-{month_day}T{hh_mm}").replace(tzinfo=TZ)


def test_eea_timeline_is_ordered_and_ends_normal() -> None:
    times = [when for when, _ in EEA_TIMELINE]
    assert times == sorted(set(times))
    assert all(when.tzinfo is TZ for when in times)
    assert EEA_TIMELINE[-1][1] == "Normal"


@pytest.mark.parametrize(
    ("t", "level"),
    [
        (ct("13"), "Normal"),  # replay start
        (ct("15", "00:00"), "Normal"),
        (ct("15", "00:15"), "EEA1"),  # a level applies from the instant it takes effect
        (ct("15", "01:15"), "EEA2"),  # EEA3 lands mid-interval, after this one starts
        (ct("15", "02:00"), "EEA3"),  # outages begin
        (ct("19", "08:45"), "EEA3"),
        (ct("19", "09:00"), "EEA2"),
        (ct("19", "10:30"), "EEA1"),
        (ct("19", "10:45"), "Normal"),
    ],
)
def test_eea_at(t: datetime, level: str) -> None:
    assert eea_at(t) == level


# --- UriParquetSource ---------------------------------------------------------


@pytest.fixture(scope="module")
def frames() -> list[Frame]:
    return UriParquetSource().frames()


def at(frames: list[Frame], t: datetime) -> Frame:
    return next(f for f in frames if f.t == t)


def test_frames_cover_the_default_window(frames: list[Frame]) -> None:
    assert len(frames) == 960
    assert [f.i for f in frames] == list(range(960))
    assert frames[0].t == ct("10") and frames[-1].t == ct("19", "23:45")
    assert all(b.t - a.t == TICK for a, b in pairwise(frames))
    assert all(f.t.tzinfo is TZ for f in frames)
    assert not any(math.isnan(f.price) or math.isnan(f.temp_f) for f in frames)


def test_frames_carry_the_eea_timeline(frames: list[Frame]) -> None:
    assert frames[0].eea == "Normal"
    assert at(frames, ct("15", "02:00")).eea == "EEA3"
    assert at(frames, ct("19", "09:00")).eea == "EEA2"
    assert at(frames, ct("19", "10:45")).eea == "Normal"


def test_window_max_price(frames: list[Frame]) -> None:
    assert max(f.price for f in frames) == 9902.08


def test_window_min_temperature(frames: list[Frame]) -> None:
    coldest = min(frames, key=lambda f: f.temp_f)
    assert coldest.temp_f == pytest.approx(4.5, abs=1)
    assert abs(coldest.t - ct("16", "08:00")) <= timedelta(hours=1)


def test_temperature_is_linear_between_hours(frames: list[Frame]) -> None:
    on_hour, next_hour = at(frames, ct("16", "08:00")), at(frames, ct("16", "09:00"))
    half = at(frames, ct("16", "08:30"))
    assert half.temp_f == pytest.approx((on_hour.temp_f + next_hour.temp_f) / 2)


def test_custom_window_restarts_the_index() -> None:
    frames = UriParquetSource().frames(ct("15"), ct("16"))
    assert len(frames) == 96
    assert frames[0].i == 0 and frames[0].t == ct("15")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (ct("09"), ct("11")),  # before the data starts
        (datetime(2021, 2, 13), datetime(2021, 2, 14)),  # naive
        (ct("13", "00:05"), ct("14")),  # off the 15-minute grid
        (ct("14"), ct("13")),  # empty
    ],
)
def test_bad_windows_raise(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError):
        UriParquetSource().frames(start, end)


def copy_data_dropping(tmp_path: Path, name: str, time_col: str, t: datetime) -> Path:
    """A copy of data/ with every row at `t` removed from one file."""
    for f in (UriParquetSource.PRICE_FILE, UriParquetSource.TEMP_FILE):
        shutil.copy(DATA_DIR / f, tmp_path / f)
    df = pd.read_parquet(DATA_DIR / name)
    df[df[time_col] != pd.Timestamp(t)].to_parquet(tmp_path / name)
    return tmp_path


def test_price_gap_raises(tmp_path: Path) -> None:
    data = copy_data_dropping(tmp_path, UriParquetSource.PRICE_FILE, "Interval Start", ct("15", "02:00"))
    with pytest.raises(ValueError, match="price: 1 missing"):
        UriParquetSource(data).frames()


def test_temperature_gap_raises(tmp_path: Path) -> None:
    data = copy_data_dropping(tmp_path, UriParquetSource.TEMP_FILE, "time", ct("16", "08:00"))
    with pytest.raises(ValueError, match="hourly temperature: 1 missing"):
        UriParquetSource(data).frames()
