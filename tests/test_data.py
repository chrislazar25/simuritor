"""The Uri data source: EEA timeline."""

from datetime import datetime

import pytest

from backend.data import EEA_TIMELINE, TZ, eea_at


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
