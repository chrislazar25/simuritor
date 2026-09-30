"""Stage what the static demo loads at runtime into `frontend/public/py/`.

- `backend/*.py`, `bridge.py` and `data/*.parquet`, which the Pyodide worker mounts and imports;
- `files.json`, the list of them;
- `safe-contract.json`: `/api/safe-contract` answers for the common terms (`PRESETS`), keyed by
  `bridge.sweep_key`, so "Find qualifying contract" answers instantly for those. Other terms are
  swept in the browser.

    uv run python -m scripts.static_demo.prepare
"""

import asyncio
import json
import multiprocessing
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from backend.safe_contract import safe_contract
from backend.schema import SweepParams

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "public" / "py"

PRESETS = (
    SweepParams(),
    SweepParams(skip_before_storm=True),
    SweepParams(standard_backup_h=4),
    SweepParams(standard_backup_h=12),
    SweepParams(policy="naive"),
    SweepParams(headroom_mode="sell"),
    SweepParams(spread_by_domain=True),
    SweepParams(emergency_uncapped=True),
)


def stage_files() -> list[str]:
    if OUT.exists():
        shutil.rmtree(OUT)
    files = []
    for src in sorted((ROOT / "backend").glob("*.py")):
        files.append(f"backend/{src.name}")
    files.append("bridge.py")
    for src in sorted((ROOT / "data").glob("*.parquet")):
        files.append(f"data/{src.name}")
    for rel in files:
        src = Path(__file__).parent / rel if rel == "bridge.py" else ROOT / rel
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (OUT / "files.json").write_text(json.dumps(files))
    return files


async def presets() -> dict[str, dict]:
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(mp_context=ctx) as pool:
        answers = {}
        for params in PRESETS:
            response = await safe_contract(params, pool)
            answers[params.model_dump_json()] = json.loads(response.model_dump_json())
            print("swept", params.model_dump_json(exclude_defaults=True) or "defaults")
    return answers


def main() -> None:
    files = stage_files()
    print(f"staged {len(files)} files in {OUT.relative_to(ROOT)}")
    (OUT / "safe-contract.json").write_text(json.dumps(asyncio.run(presets())))


if __name__ == "__main__":
    main()
