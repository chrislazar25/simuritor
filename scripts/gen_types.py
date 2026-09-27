"""Generate the JSON Schema and TypeScript types from backend/schema.py.

    uv run python -m scripts.gen_types            # regenerate both files
    uv run python -m scripts.gen_types --check    # exit 1 if either file is stale

Run from the repo root. Needs Node (npx) for json-schema-to-typescript.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from backend.schema import ClientMessage, SafeContractResponse, ServerMessage

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "simuritor.schema.json"
TYPES_PATH = ROOT / "frontend" / "src" / "types.ts"

JSON2TS = "json-schema-to-typescript@16.0.0"
BANNER = (
    "/* Generated from backend/schema.py by `uv run python -m scripts.gen_types`.\n"
    " * Do not edit by hand. */"
)


def build_schema() -> dict[str, Any]:
    """One root schema, `Simuritor = WireMessage | SafeContractResponse`, all models in `$defs`:
    websocket messages (`WireMessage = ServerMessage | ClientMessage`) and HTTP responses."""
    defs: dict[str, Any] = {}
    roots = (
        ("ServerMessage", ServerMessage),
        ("ClientMessage", ClientMessage),
        ("SafeContractResponse", SafeContractResponse),
    )
    for name, type_ in roots:
        # Serialization mode: describes what actually goes over the wire.
        schema = TypeAdapter(type_).json_schema(mode="serialization")
        defs.update(schema.pop("$defs", {}))
        defs[name] = {"title": name, **schema}

    for model in defs.values():
        # Pydantic titles every property; json2ts would turn each into its own alias.
        for prop in model.get("properties", {}).values():
            prop.pop("title", None)

    defs["WireMessage"] = {
        "title": "WireMessage",
        "anyOf": [{"$ref": "#/$defs/ServerMessage"}, {"$ref": "#/$defs/ClientMessage"}],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Simuritor",
        "anyOf": [{"$ref": "#/$defs/WireMessage"}, {"$ref": "#/$defs/SafeContractResponse"}],
        "$defs": defs,
    }


def to_typescript(schema_json: str) -> str:
    result = subprocess.run(
        ["npx", "--yes", "-p", JSON2TS, "json2ts", "--bannerComment", BANNER],
        input=schema_json,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()

    schema_json = json.dumps(build_schema(), indent=2) + "\n"
    outputs = {SCHEMA_PATH: schema_json, TYPES_PATH: to_typescript(schema_json)}

    if args.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text() != text]
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("run: uv run python -m scripts.gen_types", file=sys.stderr)
        return 1 if stale else 0

    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
