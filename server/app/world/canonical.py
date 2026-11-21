"""Canonical serialization of generator output, for golden-hash tests and ETags."""

import dataclasses
import hashlib
import json
from typing import Any


def canonical_json(output: Any) -> str:
    data = dataclasses.asdict(output) if dataclasses.is_dataclass(output) else output
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def output_hash(output: Any) -> str:
    return hashlib.sha256(canonical_json(output).encode()).hexdigest()
