"""The backend app: health check, the replay websocket and its params, the session's playback rules,
and the safe-contract endpoint."""

import asyncio
from datetime import datetime

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from backend import app as app_module
from backend.app import ReplaySession, app
from backend.data import TICK, TZ, UriParquetSource
from backend.safe_contract import CONTRACTS, SEEDS
from backend.schema import (
    InitMessage,
    PauseMessage,
    PlayMessage,
    ReplayParams,
    ResetMessage,
    SafeContractResponse,
    SpeedMessage,
    SweepParams,
    TickMessage,
    server_message,
)
from backend.serialize import build_sim
from backend.sim import Sim


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def receive(ws: WebSocketTestSession) -> InitMessage | TickMessage:
    return server_message.validate_json(ws.receive_text())


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ws_play_streams_ticks_and_reset_resends_init(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        init = receive(ws)
        assert isinstance(init, InitMessage)
        assert init.n_ticks == 960 and len(init.homes) == 3000
        assert init.params == ReplayParams()

        ws.send_text(SpeedMessage(ticks_per_sec=64).model_dump_json())
        ws.send_text(PlayMessage().model_dump_json())
        ticks = [receive(ws) for _ in range(3)]
        assert all(isinstance(t, TickMessage) for t in ticks)
        assert [t.i for t in ticks] == [0, 1, 2]
        assert all([h.id for h in t.homes] == [h.id for h in init.homes] for t in ticks)

        ws.send_text(ResetMessage().model_dump_json())
        after: list[TickMessage] = []
        msg = receive(ws)
        while isinstance(msg, TickMessage):  # ticks already in flight before the reset landed
            after.append(msg)
            msg = receive(ws)
        assert isinstance(msg, InitMessage) and msg == init  # same seed, same fleet
        assert len(after) < 5


def test_ws_query_params_set_the_replay_and_init_echoes_them(client: TestClient) -> None:
    query = "contract=0.2&homes=40&policy=naive&skip_before_storm=true&standard_backup_h=4"
    with client.websocket_connect(f"/ws?{query}") as ws:
        init = receive(ws)
        assert isinstance(init, InitMessage)
        expected = ReplayParams(contract=0.2, homes=40, policy="naive", skip_before_storm=True, standard_backup_h=4)
        assert init.params == expected
        assert len(init.homes) == 40


def test_ws_scenario_normal_replays_the_normal_week(client: TestClient) -> None:
    with client.websocket_connect("/ws?scenario=normal&homes=20") as ws:
        init = receive(ws)
        assert isinstance(init, InitMessage)
        assert init.params.scenario == "normal"
        assert init.start == datetime(2022, 2, 21, tzinfo=TZ) and init.n_ticks == 7 * 96


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("contract=1.5", "contract: Input should be less than or equal to 1"),
        ("homes=0", "homes: Input should be greater than or equal to 1"),
        ("policy=greedy", "policy: Input should be 'contract' or 'naive'"),
        ("colour=red", "colour: Extra inputs are not permitted"),
        ("scenario=katrina", "scenario: Input should be 'uri' or 'normal'"),
        ("fault_rate=abc&homes=0", "fault_rate: Input should be a valid number"),
    ],
)
def test_ws_bad_params_close_the_socket_with_a_reason(client: TestClient, query: str, reason: str) -> None:
    with client.websocket_connect(f"/ws?{query}") as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason.startswith(reason)


# --- Playback rules, on a 4-tick replay ---------------------------------------


def short_sim(params: ReplayParams) -> Sim:
    start = datetime(2021, 2, 15, tzinfo=TZ)
    frames = UriParquetSource().frames(start, start + 4 * TICK)
    return build_sim(params, params.scenario, params.contract, frames=frames)


async def next_message(queue: asyncio.Queue, timeout: float = 1.0) -> InitMessage | TickMessage:
    return await asyncio.wait_for(queue.get(), timeout)


async def nothing_arrives(queue: asyncio.Queue, within: float = 0.2) -> bool:
    await asyncio.sleep(within)
    return queue.empty()


def run_session(scenario) -> None:
    """Run `scenario(session, queue)` while the session's messages are pumped into `queue`."""

    async def main() -> None:
        session = ReplaySession(new_sim=short_sim)
        queue: asyncio.Queue = asyncio.Queue()

        async def pump() -> None:
            async for msg in session.messages():
                await queue.put(msg)

        pumping = asyncio.create_task(pump())
        try:
            await scenario(session, queue)
        finally:
            pumping.cancel()

    asyncio.run(main())


def test_session_starts_paused() -> None:
    async def scenario(session: ReplaySession, queue: asyncio.Queue) -> None:
        assert isinstance(await next_message(queue), InitMessage)
        assert await nothing_arrives(queue)

    run_session(scenario)


def test_session_pauses_itself_at_the_end() -> None:
    async def scenario(session: ReplaySession, queue: asyncio.Queue) -> None:
        await next_message(queue)
        session.handle(SpeedMessage(ticks_per_sec=64))
        session.handle(PlayMessage())
        assert [(await next_message(queue)).i for _ in range(4)] == [0, 1, 2, 3]
        assert await nothing_arrives(queue)
        assert not session.playing
        session.handle(PlayMessage())  # play at the end does nothing
        assert await nothing_arrives(queue)
        session.handle(ResetMessage())
        assert isinstance(await next_message(queue), InitMessage)

    run_session(scenario)


def test_session_pause_stops_ticks() -> None:
    async def scenario(session: ReplaySession, queue: asyncio.Queue) -> None:
        await next_message(queue)
        session.handle(PlayMessage())  # default 8 ticks/s
        assert (await next_message(queue)).i == 0
        session.handle(PauseMessage())
        assert await nothing_arrives(queue, within=0.4)  # 3 tick intervals

    run_session(scenario)


# --- GET /api/safe-contract ---------------------------------------------------


def test_safe_contract_curve_is_warmed_at_startup_and_cached_by_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """A small fleet so the 78 replays run fast; the lifespan starts it and shuts the worker pool down."""
    monkeypatch.setattr(app_module, "safe_contract_cache", type(app_module.safe_contract_cache)())
    monkeypatch.setattr(app_module, "WARM_SAFE_CONTRACT", (SweepParams(homes=20, max_calls_per_day=2),))
    with TestClient(app) as client:
        assert list(app_module.safe_contract_cache) == [SweepParams(homes=20, max_calls_per_day=2)]
        response = client.get("/api/safe-contract?homes=20&max_calls_per_day=2")
        assert response.status_code == 200
        body = SafeContractResponse.model_validate(response.json())
        assert body.params.homes == 20 and body.params.max_calls_per_day == 2
        assert body.seeds == list(SEEDS)
        assert [c.scenario for c in body.scenarios] == ["uri", "normal"]
        for curve in body.scenarios:
            assert [p.contract for p in curve.curve] == list(CONTRACTS)
            assert curve.safe is None or curve.safe in CONTRACTS
            assert all(p.kept is not None for p in curve.curve)
        uri, normal = body.scenarios
        assert all(p.pre_kept is not None for p in uri.curve) and all(p.pre_kept is None for p in normal.curve)

        again = client.get("/api/safe-contract?max_calls_per_day=2&homes=20")
        assert again.json() == response.json()
        assert len(app_module.safe_contract_cache) == 1


def test_a_failed_safe_contract_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def flaky(params: SweepParams, pool: object) -> SafeContractResponse:
        calls.append(params)
        if len(calls) == 1:
            raise RuntimeError("worker died")
        return SafeContractResponse(params=params, seeds=list(SEEDS), scenarios=[])

    monkeypatch.setattr(app_module, "safe_contract_cache", type(app_module.safe_contract_cache)())
    monkeypatch.setattr(app_module, "safe_contract", flaky)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/safe-contract?homes=7").status_code == 500
    assert client.get("/api/safe-contract?homes=7").status_code == 200
    assert client.get("/api/safe-contract?homes=7").status_code == 200
    assert len(calls) == 2


@pytest.mark.parametrize("query", ["contract=0.3", "scenario=uri", "homes=0", "headroom_mode=hoard"])
def test_safe_contract_rejects_bad_params(client: TestClient, query: str) -> None:
    assert client.get(f"/api/safe-contract?{query}").status_code == 422
