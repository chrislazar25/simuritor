"""The backend app: health check, the replay websocket, and the session's playback rules."""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from backend.app import ReplaySession, app
from backend.data import TICK, TZ, UriParquetSource
from backend.schema import (
    InitMessage,
    PauseMessage,
    PlayMessage,
    ResetMessage,
    SpeedMessage,
    TickMessage,
    server_message,
)
from backend.sim import Sim, uri_replay


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
        assert init.n_ticks == 960 and len(init.homes) == 500

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


# --- Playback rules, on a 4-tick replay ---------------------------------------


def short_sim() -> Sim:
    start = datetime(2021, 2, 15, tzinfo=TZ)
    return uri_replay(frames=UriParquetSource().frames(start, start + 4 * TICK))


async def next_message(queue: asyncio.Queue, timeout: float = 1.0) -> InitMessage | TickMessage:
    return await asyncio.wait_for(queue.get(), timeout)


async def nothing_arrives(queue: asyncio.Queue, within: float = 0.2) -> bool:
    await asyncio.sleep(within)
    return queue.empty()


def run_session(scenario) -> None:
    """Run `scenario(session, queue)` while the session's messages are pumped into `queue`."""

    async def main() -> None:
        session = ReplaySession(short_sim)
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
