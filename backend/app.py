"""Simuritor backend: a health check and the replay websocket.

The websocket handler only moves messages. It pumps a session's outgoing
messages to the socket and hands validated client messages back to it. What
gets sent is up to the session, so the real replay loop replaces
`FixtureSession` without touching the connection code.

Run: uv run uvicorn backend.app:app --reload --port 8000
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.schema import (
    ClientMessage,
    InitMessage,
    TickMessage,
    client_message,
    server_message,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

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


def load_fixture[M: (InitMessage, TickMessage)](name: str, kind: type[M]) -> M:
    msg = server_message.validate_json((FIXTURES / name).read_text())
    if not isinstance(msg, kind):
        raise TypeError(f"{name}: expected {kind.__name__}, got {type(msg).__name__}")
    return msg


class FixtureSession:
    """Stub until the replay loop lands: the sample init, then the sample tick once per interval.

    Only `i` and `t` advance between ticks, so a client can see them arriving.
    """

    def __init__(self, interval_s: float = 1.0) -> None:
        self.init = load_fixture("init_sample.json", InitMessage)
        self.tick = load_fixture("tick_sample.json", TickMessage)
        self.interval_s = interval_s

    async def messages(self) -> AsyncIterator[InitMessage | TickMessage]:
        yield self.init
        step = (self.init.end - self.init.start) / self.init.n_ticks
        i = self.tick.i
        while True:
            yield self.tick.model_copy(update={"i": i, "t": self.init.start + i * step})
            i = (i + 1) % self.init.n_ticks
            await asyncio.sleep(self.interval_s)

    def handle(self, msg: ClientMessage) -> None:
        log.info("client message (stub ignores it): %s", msg.model_dump_json())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def replay_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session: Session = FixtureSession()
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
        session.handle(msg)
