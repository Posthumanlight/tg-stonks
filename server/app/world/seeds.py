"""Seed derivation. Every RNG in world-gen comes from here (docs/world-gen.md, rule 1-2)."""

import hashlib
import random


def derive_seed(world_seed: int, path: str, stream: str) -> int:
    """Stable 64-bit seed for one RNG stream of one object. Never use `hash()`."""
    digest = hashlib.blake2b(
        f"{world_seed}:{path}:{stream}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big")


def make_rng(
    world_seed: int, path: str, stream: str, attempt: int = 0
) -> random.Random:
    """RNG for `stream` of the object at `path`; `attempt` > 0 for generate-and-validate retries."""
    if attempt:
        stream = f"{stream}/attempt/{attempt}"
    return random.Random(derive_seed(world_seed, path, stream))
