"""The backend's replay and safe-contract logic behind plain functions, for the static demo.

The static build runs the unchanged `backend/` package in the browser with Pyodide (no FastAPI,
no process pool). `frontend/src/static/sim.worker.ts` loads this module and calls it; every value
crossing into JavaScript is a JSON string or a plain dict. Same params and seeds, same numbers as
the server.
"""

import json
import math
from dataclasses import asdict
from urllib.parse import parse_qsl

import numpy as np
from pydantic import ValidationError

from backend import safe_contract as sc
from backend.schema import ReplayParams, SafeContractCurve, SafeContractResponse, SweepParams
from backend.serialize import init_message, replay_sim, tick_message
from backend.sim import Sim

MAX_REASON_BYTES = 123
"""Same limit as the server's websocket close reason."""


def reject_reason(err: ValidationError) -> str:
    """Mirrors `backend.app.close_reason` (not imported: that module needs FastAPI)."""
    e = err.errors(include_url=False)[0]
    reason = f"{'.'.join(map(str, e['loc'])) or 'params'}: {e['msg']}"
    if len(err.errors()) > 1:
        reason += f" (+{len(err.errors()) - 1} more)"
    return reason.encode()[:MAX_REASON_BYTES].decode(errors="ignore")


class Replay:
    """One replay; the worker's JavaScript owns the play/pause/speed loop around it."""

    def __init__(self, params: ReplayParams) -> None:
        self.params = params
        self.sim: Sim = replay_sim(params)

    def reset(self) -> str:
        self.sim = replay_sim(self.params)
        return self.init()

    def init(self) -> str:
        return init_message(self.sim, self.params).model_dump_json()

    def done(self) -> bool:
        return self.sim.done

    def step(self) -> str:
        return tick_message(self.sim.fleet, self.sim.step()).model_dump_json()


def open_replay(query: str) -> dict:
    """`{"replay": Replay}` for valid `/ws` query params, else `{"reject": reason}`."""
    try:
        params = ReplayParams.model_validate(dict(parse_qsl(query)))
    except ValidationError as err:
        return {"reject": reject_reason(err)}
    return {"replay": Replay(params)}


def sweep_params(query: str) -> SweepParams:
    return SweepParams.model_validate(dict(parse_qsl(query)))


def sweep_key(query: str) -> str:
    """The canonical key for `/api/safe-contract` query params (defaults filled in)."""
    return sweep_params(query).model_dump_json()


def sweep_jobs() -> str:
    """Every (scenario, contract, seed) the sweep replays, as JSON."""
    contracts = (None, *sc.CONTRACTS)
    return json.dumps([[s, c, seed] for s in sc.SCENARIO_ORDER for c in contracts for seed in sc.SEEDS])


def summarise(query: str, job_json: str) -> str:
    """One `sweep_jobs` entry's headless replay summary, as JSON (NaN encoded as null). The job
    comes as JSON because a JavaScript null would arrive as `JsNull`, not None."""
    scenario, contract, seed = json.loads(job_json)
    s = sc.summarise(sweep_params(query), scenario, contract, seed)
    return json.dumps({k: None if isinstance(v, float) and math.isnan(v) else v for k, v in asdict(s).items()})


def aggregate(query: str, summaries_json: str) -> str:
    """The `/api/safe-contract` response from `summarise` results in `sweep_jobs` order."""
    params = sweep_params(query)
    jobs = json.loads(sweep_jobs())
    runs: dict[tuple[str, float | None], list[sc.Summary]] = {}
    for (scenario, contract, _), raw in zip(jobs, json.loads(summaries_json), strict=True):
        fields = {k: float("nan") if v is None else v for k, v in raw.items()}
        runs.setdefault((scenario, contract), []).append(sc.Summary(**fields))
    curves = []
    for scenario in sc.SCENARIO_ORDER:
        baseline = float(np.mean([r.critical_ran_out for r in runs[scenario, None]]))
        curve = [sc.point(c, runs[scenario, c]) for c in sc.CONTRACTS]
        curves.append(
            SafeContractCurve(
                scenario=scenario, curve=curve, baseline_critical_ran_out=baseline, safe=sc.safest(curve, baseline)
            )
        )
    return SafeContractResponse(params=params, seeds=list(sc.SEEDS), scenarios=curves).model_dump_json()
