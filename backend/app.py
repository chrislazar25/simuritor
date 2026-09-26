"""Simuritor backend: a health check and the replay websocket.

The websocket handler only moves messages. It pumps a session's outgoing
messages to the socket and hands validated client messages back to it. What
gets sent is up to the session: `ReplaySession` steps a fresh sim for each
connection.

Run: uv run uvicorn backend.app:app --reload --port 8000
     SIMURITOR_POLICY=naive uv run uvicorn ...   (the baseline; default `contract`)
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.policy import POLICIES
from backend.schema import (
    ClientMessage,
    InitMessage,
    PauseMessage,
    PlayMessage,
    ResetMessage,
    SpeedMessage,
    TickMessage,
    client_message,
)
from backend.serialize import init_message, tick_message
from backend.sim import Sim, uri_replay

DEFAULT_TICKS_PER_SEC = 8.0
POLICY = os.environ.get("SIMURITOR_POLICY", "contract")
"""A name from `backend.policy.POLICIES`."""
if POLICY not in POLICIES:
    raise ValueError(f"SIMURITOR_POLICY={POLICY!r}; expected one of {sorted(POLICIES)}")

# uvicorn configures this logger, so our lines show up in the server console.
log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Simuritor")


class Session(Protocol):
    """One replay, owned by one websocket connection."""

    def messages(self) -> AsyncIterator[InitMessage | TickMessage]:
        """Everything to send to the client, in order, for the life of the connection."""
        ...

    def handle(self, msg: ClientMessage) -> None:
        """React to a validated client message."""
        ...


class ReplaySession:
    """Starts paused at tick 0. Play steps the sim at `ticks_per_sec`; it pauses itself after the last tick.

    Reset builds a fresh sim (same seed, so the same replay), pauses, and resends `init`.
    Speed survives a reset.
    """

    def __init__(self, new_sim: Callable[[], Sim] = partial(uri_replay, policy=POLICY)) -> None:
        self.new_sim = new_sim
        self.sim = new_sim()
        self.playing = False
        self.ticks_per_sec = DEFAULT_TICKS_PER_SEC
        self.reset_requested = False
        self.wake = asyncio.Event()
        """Set by `handle` so a waiting or sleeping `messages` loop re-checks its state now."""

    async def messages(self) -> AsyncIterator[InitMessage | TickMessage]:
        loop = asyncio.get_running_loop()
        yield init_message(self.sim)
        while True:
            if self.reset_requested:
                self.reset_requested = False
                self.sim = self.new_sim()
                yield init_message(self.sim)
            elif self.playing and not self.sim.done:
                due = loop.time() + 1 / self.ticks_per_sec
                yield tick_message(self.sim.fleet, self.sim.step())
                if self.sim.done:
                    self.playing = False
                # Sleep only what's left of the interval, so stepping and sending don't slow the rate.
                await self.sleep(max(0.0, due - loop.time()))
            else:
                await self.wake.wait()
                self.wake.clear()

    async def sleep(self, seconds: float) -> None:
        """Wait between ticks, but wake early for pause, speed or reset."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.wake.wait(), seconds)
        self.wake.clear()

    def handle(self, msg: ClientMessage) -> None:
        match msg:
            case PlayMessage():
                self.playing = not self.sim.done
            case PauseMessage():
                self.playing = False
            case SpeedMessage(ticks_per_sec=tps):
                self.ticks_per_sec = tps
            case ResetMessage():
                self.playing = False
                self.reset_requested = True
        self.wake.set()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def replay_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session: Session = ReplaySession()
    tasks = [
        asyncio.create_task(send_all(websocket, session)),
        asyncio.create_task(receive_all(websocket, session)),
    ]
    # Whichever side stops first (usually the client disconnecting) ends the session.
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(WebSocketDisconnect):
            task.result()


async def send_all(websocket: WebSocket, session: Session) -> None:
    async for msg in session.messages():
        await websocket.send_text(msg.model_dump_json())


async def receive_all(websocket: WebSocket, session: Session) -> None:
    """Validate each client message and pass it on. Invalid ones are logged and dropped; the socket stays open."""
    while True:
        frame = await websocket.receive()
        if frame["type"] == "websocket.disconnect":
            return
        raw = frame.get("text") or frame.get("bytes") or ""
        try:
            msg = client_message.validate_json(raw)
        except ValidationError as err:
            log.warning("ignoring invalid client message %.200r: %s", raw, err.errors(include_url=False))
            continue
        log.info("client message: %s", msg.model_dump_json())
        session.handle(msg)
