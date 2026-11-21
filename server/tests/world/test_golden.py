"""Golden hashes: generator output must not change without a version bump.

If one of these fails, you changed generated output. Either revert, or bump the
generator's VERSION (keeping the old version registered while pins use it), add an entry
to the version log in docs/world-gen.md, and add the new version's hashes here.

Content tuning (content/worldgen/*.toml) also changes output. Before launch that's
fine: update the hashes. See "Content and versions" in docs/world-gen.md.
"""

import pytest

from app.content.worldgen import WorldgenContent
from app.world.canonical import output_hash
from app.world.galaxy import v1 as galaxy_v1
from app.world.planet import v1 as planet_v1
from app.world.system import v1 as system_v1

GALAXY_V1 = {
    42: "6515bb33fc5131c88612dbe60ca02095abb68b0c3267eb3d51ea2bc211732ff6",
    7: "156829dd27a6db1e03dcecf79126b953e4a982a8f54887fd07424228fd2ad4aa",
}
# (seed, star) -> hash of the skeleton plus all of its planets.
SYSTEM_PLANET_V1 = {
    (42, 0): "88ccb58c3c3418d43bca56dfd3e28c6031521e3a26a8a813b7f363c6486ffa98",
    (42, 57): "7be1c1c2d88d44d80cbe77e8a6ffc9fee59b638a47dd0098d076ac9773d176a7",
    (7, 99): "a599d714609a6310bab5c93db90f5f94af8a77a80b463e7b892023e985a45206",
}


@pytest.mark.parametrize("seed", sorted(GALAXY_V1))
def test_galaxy_v1(seed: int, content: WorldgenContent) -> None:
    assert output_hash(galaxy_v1.generate(seed, content)) == GALAXY_V1[seed]


@pytest.mark.parametrize(("seed", "star"), sorted(SYSTEM_PLANET_V1))
def test_system_and_planet_v1(seed: int, star: int, content: WorldgenContent) -> None:
    skeleton = system_v1.generate(seed, star, content)
    planets = [
        planet_v1.generate(seed, skeleton, s.index, content) for s in skeleton.slots
    ]
    combined = output_hash([output_hash(skeleton)] + [output_hash(p) for p in planets])
    assert combined == SYSTEM_PLANET_V1[(seed, star)]
