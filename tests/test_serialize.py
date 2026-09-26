"""The serializer: real sim output becomes valid, self-consistent wire messages."""

import pytest

from backend.data import TICK
from backend.schema import InitMessage, TickMessage, server_message
from backend.serialize import init_message, tick_message
from backend.sim import uri_replay


@pytest.fixture(scope="module")
def messages() -> tuple[InitMessage, list[TickMessage]]:
    sim = uri_replay(seed=0)
    init = init_message(sim)
    ticks = []
    while not sim.done:
        ticks.append(tick_message(sim.fleet, sim.step()))
    return init, ticks


def test_init_describes_the_replay(messages: tuple[InitMessage, list[TickMessage]]) -> None:
    init, ticks = messages
    assert init.n_ticks == len(ticks) == 960
    assert init.start == ticks[0].t and init.end == ticks[-1].t + TICK
    assert len({h.id for h in init.homes}) == len(init.homes) == 500
    assert all(h.tier == "critical" for h in init.homes if h.household == "medical")
    assert sum(h.tier == "none" for h in init.homes) == sum(h.tier == "critical" for h in init.homes) == 50


def test_messages_round_trip_through_json(messages: tuple[InitMessage, list[TickMessage]]) -> None:
    init, ticks = messages
    for msg in (init, ticks[0], ticks[212], ticks[-1]):
        assert server_message.validate_json(msg.model_dump_json()) == msg


def test_every_tick_keeps_the_contract_consistent(messages: tuple[InitMessage, list[TickMessage]]) -> None:
    """The same rules `tests/test_contract.py` checks on the fixture, on every real tick."""
    init, ticks = messages
    ids = [h.id for h in init.homes]
    backup = [h.tier != "none" for h in init.homes]
    for tick in ticks:
        homes, fleet = tick.homes, tick.fleet
        assert [h.id for h in homes] == ids
        assert fleet.homes_on_grid == sum(h.grid for h in homes)
        assert fleet.homes_on_battery == sum(not h.grid and b and h.soc > 0 for h, b in zip(homes, backup))
        assert fleet.homes_dark == sum(not h.grid and b and h.soc == 0 for h, b in zip(homes, backup))
        assert fleet.homes_dark_by_contract == sum(not h.grid and not b for h, b in zip(homes, backup))
        assert fleet.homes_exporting == sum(h.grid and h.action == "discharge" for h in homes)
        delivered_kw = sum(h.kw for h in homes if h.action == "discharge")
        assert fleet.delivered_mw == pytest.approx(delivered_kw / 1000)
        assert fleet.delivered_mw <= fleet.available_mw + 1e-12
        assert (fleet.promised_mw > 0) == fleet.utility_call
        assert all(h.src == "rule" and h.conf is None for h in homes)
    assert max(tick.fleet.homes_exporting for tick in ticks) > 0
    assert max(tick.fleet.homes_dark_by_contract for tick in ticks) > 0
    last = ticks[-1].fleet
    assert last.promise_kept is not None and last.penalty_usd > 0
