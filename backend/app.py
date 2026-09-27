"""Simuritor backend: a health check, the replay websocket and the safe-contract curve.

The websocket handler only moves messages. It validates the replay params in the
query string, pumps a session's outgoing messages to the socket and hands validated
client messages back to it. What gets sent is up to the session: `ReplaySession`
steps a fresh sim for each connection.

Run: uv run uvicorn backend.app:app --reload --port 8000
     ws://localhost:8000/ws?policy=naive&contract=0.1   (any `ReplayParams`; defaults otherwise)
"""

import asyncio
import contextlib
import functools
import logging
import multiprocessing
import os
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated, Protocol

import anyio
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from backend.safe_contract import CONTRACTS, SCENARIO_ORDER, SEEDS, safe_contract
from backend.schema import (
    ClientMessage,
    InitMessage,
    PauseMessage,
    PlayMessage,
    ReplayParams,
    ResetMessage,
    SafeContractResponse,
    SweepParams,
    SpeedMessage,
    TickMessage,
    client_message,
)
from backend.serialize import init_message, replay_sim, tick_message
from backend.sim import Sim

DEFAULT_TICKS_PER_SEC = 8.0
MAX_CLOSE_REASON_BYTES = 123
"""The websocket protocol's limit on a close frame's reason."""
SAFE_CONTRACT_CACHE_SIZE = 64
WARM_SAFE_CONTRACT = (SweepParams(), SweepParams(skip_before_storm=True))
"""Safe-contract answers computed in the background at startup (the defaults, and the defaults with
the storm clause), so the first requests for them don't wait ~12 s."""

# uvicorn configures this logger, so our lines show up in the server console.
log = logging.getLogger("uvicorn.error")


@functools.cache
def replay_pool() -> ProcessPoolExecutor:
    """Worker processes for headless replays, started on first use. Spawned, not forked: the
    server process runs threads."""
    workers = min(os.cpu_count() or 1, len(SCENARIO_ORDER) * (len(CONTRACTS) + 1) * len(SEEDS))
    return ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    warming = [safe_contract_task(params) for params in WARM_SAFE_CONTRACT]
    yield
    for task in warming:
        task.cancel()
    if replay_pool.cache_info().currsize:
        replay_pool().shutdown(cancel_futures=True)
        replay_pool.cache_clear()


app = FastAPI(title="Simuritor", lifespan=lifespan)
safe_contract_cache: OrderedDict[SweepParams, asyncio.Task[SafeContractResponse]] = OrderedDict()
"""Finished or running computations by params, so concurrent requests share one. Least recently
used out first, `SAFE_CONTRACT_CACHE_SIZE` entries."""


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

    Reset builds a fresh sim (same params and seed, so the same replay), pauses, and resends `init`.
    Speed survives a reset.
    """

    def __init__(
        self, params: ReplayParams = ReplayParams(), new_sim: Callable[[ReplayParams], Sim] = replay_sim
    ) -> None:
        self.params = params
        self.new_sim = new_sim
        self.sim = new_sim(params)
        self.playing = False
        self.ticks_per_sec = DEFAULT_TICKS_PER_SEC
        self.reset_requested = False
        self.wake = asyncio.Event()
        """Set by `handle` so a waiting or sleeping `messages` loop re-checks its state now."""

    async def messages(self) -> AsyncIterator[InitMessage | TickMessage]:
        loop = asyncio.get_running_loop()
        yield init_message(self.sim, self.params)
        while True:
            if self.reset_requested:
                self.reset_requested = False
                self.sim = self.new_sim(self.params)
                yield init_message(self.sim, self.params)
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


def safe_contract_task(params: SweepParams) -> asyncio.Task[SafeContractResponse]:
    """The cached computation for `params`, started if there's none (or the last one failed)."""
    task = safe_contract_cache.get(params)
    if task is not None and not (task.done() and (task.cancelled() or task.exception() is not None)):
        safe_contract_cache.move_to_end(params)
        return task
    task = asyncio.create_task(timed_safe_contract(params))
    safe_contract_cache[params] = task
    if len(safe_contract_cache) > SAFE_CONTRACT_CACHE_SIZE:
        safe_contract_cache.popitem(last=False)
    return task


async def timed_safe_contract(params: SweepParams) -> SafeContractResponse:
    started = time.perf_counter()
    try:
        response = await safe_contract(params, replay_pool())
    except Exception:
        log.exception("safe-contract failed: %s", params.model_dump_json())  # a warm-up has no caller to see it
        raise
    log.info("safe-contract in %.1f s: %s", time.perf_counter() - started, params.model_dump_json())
    return response


@app.get("/api/safe-contract")
async def get_safe_contract(params: Annotated[SweepParams, Query()]) -> SafeContractResponse:
    """Promise kept, contract P&L and backup cost against contract size, and the largest safe
    contract (`backend/safe_contract.py`). Cached by params; the defaults are warmed at startup."""
    # Shielded: a client giving up doesn't cancel a computation others may be waiting on.
    return await asyncio.shield(safe_contract_task(params))


@app.websocket("/ws")
async def replay_socket(websocket: WebSocket) -> None:
    """Query params are `ReplayParams`; invalid ones close the socket (1008) with the reason."""
    await websocket.accept()
    try:
        params = ReplayParams.model_validate(dict(websocket.query_params))
    except ValidationError as err:
        await websocket.close(status.WS_1008_POLICY_VIOLATION, close_reason(err))
        return
    session: Session = ReplaySession(params)
    # A task group, not bare tasks, so a cancelled handler (server shutdown, a test client closing)
    # takes both halves down with it instead of leaving them orphaned mid-send.
    async with anyio.create_task_group() as group:

        async def run(half: Callable[[WebSocket, Session], Awaitable[None]]) -> None:
            with contextlib.suppress(WebSocketDisconnect):
                await half(websocket, session)
            group.cancel_scope.cancel()  # whichever side stops first (usually the client leaving) ends the session

        group.start_soon(run, send_all)
        group.start_soon(run, receive_all)


def close_reason(err: ValidationError) -> str:
    """The first invalid param and why, e.g. "contract: Input should be less than or equal to 1"."""
    e = err.errors(include_url=False)[0]
    reason = f"{'.'.join(map(str, e['loc'])) or 'params'}: {e['msg']}"
    if len(err.errors()) > 1:
        reason += f" (+{len(err.errors()) - 1} more)"
    return reason.encode()[:MAX_CLOSE_REASON_BYTES].decode(errors="ignore")


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
