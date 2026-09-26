"""Faults: rolling outages (the default), the fixed outage used in tests, and silent device faults."""

from datetime import timedelta
from itertools import groupby

import numpy as np
import pytest

from backend.data import TICK
from backend.faults import OUTAGE_END, OUTAGE_START, FixedOutage, RollingOutage, SilentDeviceFaults

N = 500


def window_ticks() -> list:
    n = (OUTAGE_END - OUTAGE_START) // TICK
    return [OUTAGE_START + k * TICK for k in range(n)]


@pytest.fixture(scope="module")
def rolling() -> RollingOutage:
    return RollingOutage(N, np.random.default_rng(0))


@pytest.fixture(scope="module")
def down(rolling: RollingOutage) -> np.ndarray:
    """(ticks, homes): True where the home is off grid, over the outage window."""
    return np.array([rolling.grid_down(t) for t in window_ticks()])


def test_groups_split_the_fleet(rolling: RollingOutage) -> None:
    sizes = {int(g): int((rolling.group == g).sum()) for g in np.unique(rolling.group)}
    assert sizes == {-1: 50, 0: 90, 1: 90, 2: 90, 3: 90, 4: 90}


def test_46_percent_out_at_every_tick(down: np.ndarray) -> None:
    # 10% never restored + 40% of the other 90% (2 of 5 groups).
    assert (down.sum(axis=1) == 50 + 180).all()


def test_never_restored_homes_are_out_the_whole_window(rolling: RollingOutage, down: np.ndarray) -> None:
    assert down[:, rolling.group < 0].all()


def test_rotating_homes_cycle_4h_off_6h_on(rolling: RollingOutage, down: np.ndarray) -> None:
    for g in range(rolling.n_groups):
        home = int(np.flatnonzero(rolling.group == g)[0])
        runs = [(off, len(list(ticks))) for off, ticks in groupby(down[:, home])]
        interior = runs[1:-1]  # the first and last runs are cut by the window edges
        assert interior and all(n == (16 if off else 24) for off, n in interior)


def test_no_outage_outside_the_window(rolling: RollingOutage) -> None:
    for t in (OUTAGE_START - TICK, OUTAGE_END, OUTAGE_END + timedelta(days=1)):
        assert not rolling.grid_down(t).any()


def test_seeded(rolling: RollingOutage) -> None:
    assert np.array_equal(RollingOutage(N, np.random.default_rng(0)).group, rolling.group)
    assert not np.array_equal(RollingOutage(N, np.random.default_rng(1)).group, rolling.group)


def test_fixed_outage_hits_an_exact_share() -> None:
    fixed = FixedOutage(N, np.random.default_rng(0), share=0.40)
    assert fixed.grid_down(OUTAGE_START).sum() == 200
    assert not fixed.grid_down(OUTAGE_END).any()


# --- Silent device faults ------------------------------------------------------


def test_device_faults_happen_at_the_rate_at_random_seconds() -> None:
    """0.02 per home-hour over 10,000 homes and 40 ticks (10 h): ~2,000 faults, 20% of them hard."""
    faults = SilentDeviceFaults(10_000, np.random.default_rng(0), rate_per_home_hour=0.02)
    ticks = [faults.tick() for _ in range(40)]
    starts = np.concatenate([t.fails_at_s[~np.isnan(t.fails_at_s)] for t in ticks])
    assert len(starts) == pytest.approx(10_000 * 0.02 * 10, rel=0.1)
    assert starts.min() >= 0 and starts.max() < 900 and np.median(starts) == pytest.approx(450, rel=0.1)
    assert faults.hard.sum() == pytest.approx(0.2 * len(starts), rel=0.15)


def test_a_transient_fault_is_back_next_tick() -> None:
    faults = SilentDeviceFaults(100, np.random.default_rng(0), rate_per_home_hour=1e6, transient_frac=1.0)
    for _ in range(3):
        t = faults.tick()
        assert not t.out.any() and not np.isnan(t.fails_at_s).any()  # every home, every tick; none stays out


def test_a_hard_fault_is_out_for_the_rest_of_the_replay_and_known() -> None:
    faults = SilentDeviceFaults(100, np.random.default_rng(0), rate_per_home_hour=1e6, transient_frac=0.0)
    first = faults.tick()
    assert not first.out.any() and not np.isnan(first.fails_at_s).any()  # silent: not known this tick
    for _ in range(3):
        t = faults.tick()
        assert t.out.all() and np.isnan(t.fails_at_s).all()  # known out; can't fault again


def test_device_faults_are_seeded() -> None:
    a, b = (SilentDeviceFaults(N, np.random.default_rng(7)) for _ in range(2))
    for _ in range(200):
        ta, tb = a.tick(), b.tick()
        assert np.array_equal(ta.fails_at_s, tb.fails_at_s, equal_nan=True) and np.array_equal(ta.out, tb.out)
