"""The wire contract: fixtures are valid, internally consistent, and generated files are fresh."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.schema import InitMessage, ReplayParams, ScenarioParams, TickMessage, client_message, server_message

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


def load(name: str):
    return server_message.validate_json((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def init() -> InitMessage:
    msg = load("init_sample.json")
    assert isinstance(msg, InitMessage)
    return msg


@pytest.fixture(scope="module")
def tick() -> TickMessage:
    msg = load("tick_sample.json")
    assert isinstance(msg, TickMessage)
    return msg


def test_fixtures_round_trip(init: InitMessage, tick: TickMessage) -> None:
    for name, msg in (("init_sample.json", init), ("tick_sample.json", tick)):
        assert json.loads(msg.model_dump_json()) == json.loads((FIXTURES / name).read_text())


def test_tick_covers_exactly_the_init_homes(init: InitMessage, tick: TickMessage) -> None:
    init_ids = [h.id for h in init.homes]
    assert len(set(init_ids)) == len(init_ids), "duplicate home ids in init"
    assert [h.id for h in tick.homes] == init_ids


def test_medical_homes_are_critical(init: InitMessage) -> None:
    assert all(h.tier == "critical" for h in init.homes if h.household == "medical")


def test_tick_is_inside_the_replay_window(init: InitMessage, tick: TickMessage) -> None:
    assert 0 <= tick.i < init.n_ticks
    assert init.start <= tick.t < init.end


def test_fleet_stats_match_homes(init: InitMessage, tick: TickMessage) -> None:
    homes, fleet = tick.homes, tick.fleet
    backup = [h.tier != "none" for h in init.homes]
    assert fleet.homes_on_grid == sum(h.grid for h in homes)
    assert fleet.homes_on_battery == sum(not h.grid and b and h.soc > 0 for h, b in zip(homes, backup))
    assert fleet.homes_dark == sum(not h.grid and b and h.soc == 0 for h, b in zip(homes, backup))
    assert fleet.homes_dark_by_contract == sum(not h.grid and not b for h, b in zip(homes, backup))
    assert fleet.homes_exporting == sum(h.grid and h.action == "discharge" for h in homes)
    delivered_kw = sum(h.kw for h in homes if h.action == "discharge")
    assert fleet.delivered_mw == pytest.approx(delivered_kw / 1000)
    assert fleet.delivered_mw <= fleet.available_mw
    assert fleet.utility_call == (fleet.promised_mw is not None and fleet.promised_mw > 0)
    money = fleet.contract_pnl_usd - fleet.backup_cost_usd + fleet.market_usd
    assert money == pytest.approx(fleet.revenue_usd, abs=0.02)


def test_init_echoes_params_that_match_it(init: InitMessage) -> None:
    assert len(init.homes) == init.params.homes


def test_replay_params_default_and_parse_query_strings() -> None:
    assert ReplayParams().model_dump() == {
        "policy": "contract",
        "standard_backup_h": 8.0,
        "max_calls_per_day": 1,
        "emergency_uncapped": False,
        "skip_before_storm": False,
        "fault_rate": 0.001,
        "headroom_mode": "keep",
        "homes": 500,
        "scenario": "uri",
        "contract": 0.3,
    }
    query = {"contract": "0.1", "homes": "50", "emergency_uncapped": "true", "headroom_mode": "sell"}
    params = ReplayParams.model_validate(query)
    assert (params.contract, params.homes, params.emergency_uncapped, params.headroom_mode) == (0.1, 50, True, "sell")


@pytest.mark.parametrize(
    "query",
    [
        {"contract": "1.5"},
        {"contract": "-0.1"},
        {"homes": "0"},
        {"homes": "100000"},
        {"homes": "12.5"},
        {"policy": "greedy"},
        {"headroom_mode": "hoard"},
        {"scenario": "katrina"},
        {"fault_rate": "abc"},
        {"standard_backup_h": "-1"},
        {"max_calls_per_day": "-1"},
        {"skip_before_storm": "maybe"},
        {"colour": "red"},
    ],
)
def test_invalid_replay_params(query: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ReplayParams.model_validate(query)


def test_scenario_params_have_no_contract() -> None:
    with pytest.raises(ValidationError):
        ScenarioParams.model_validate({"contract": "0.3"})


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "play"}',
        '{"type": "pause"}',
        '{"type": "reset"}',
        '{"type": "speed", "ticks_per_sec": 0.5}',
        '{"type": "speed", "ticks_per_sec": 64}',
    ],
)
def test_valid_client_messages(raw: str) -> None:
    client_message.validate_json(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "speed", "ticks_per_sec": 0}',
        '{"type": "speed", "ticks_per_sec": 65}',
        '{"type": "speed"}',
        '{"type": "seek", "i": 10}',
        '{"type": "play", "extra": 1}',
        '{"type": "tick"}',
    ],
)
def test_invalid_client_messages(raw: str) -> None:
    with pytest.raises(ValidationError):
        client_message.validate_json(raw)


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node (npx) to generate TS types")
def test_generated_files_are_fresh() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.gen_types", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
