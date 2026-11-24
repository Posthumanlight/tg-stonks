"""Print the JSON Schema of all protocol models (input for client codegen).

Usage, from the repo root:  poetry run python server/app/cli/export_schema.py
Consumed by client/scripts/gen-protocol.mjs (`npm run gen:protocol`).
"""

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic.json_schema import models_json_schema

from app.protocol import PROTOCOL_VERSION
from app.protocol.registry import PROTOCOL_MODELS


def build_schema() -> dict[str, Any]:
    _, schema = models_json_schema(
        [(model, "serialization") for model in PROTOCOL_MODELS],
        ref_template="#/$defs/{model}",
    )
    return {"title": "Protocol", "x-protocol-version": PROTOCOL_VERSION, **schema}


if __name__ == "__main__":
    json.dump(build_schema(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
