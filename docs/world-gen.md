# World Generation

Procedural generation of the galaxy and everything in it: star clusters, star systems,
planets, and (later) planet surfaces and generated entities. This doc specifies the
galaxy, star links, stars and planets in implementable detail; surfaces and entities are
outlined with their decided constraints.

Code: `server/app/world/` (pure — no DB, network or clock; CLAUDE.md rules 2–4).
Tables: `content/worldgen/*.toml` (CLAUDE.md rule 9).

---

## Decided

### Principles
- Everything generated is a pure function of `(world_seed, object_path, generator_version)`.
  Only player-caused changes (**deltas**) are persisted, never generated data.
- **One persistent galaxy**: the live server has a single world with a single `world_seed`.
- Generators run **server-side only**. The client never re-implements them; it receives
  serialized generator output (see [Delivery to the client](#delivery-to-the-client)).
- Code does structure and placement; all tunable numbers and weighted tables live in
  `content/worldgen/*.toml`, validated by Pydantic at startup (invalid content fails fast).
- Changing any generator's output requires bumping that generator's version and adding an
  entry to the [Generator version log](#generator-version-log).

### Scope at launch
| Level | Status |
|---|---|
| Galaxy: 2D ellipse, 100 stars in clusters with voids, travel links | **Specified here** |
| Star system: one main-sequence star + 0–8 planets, static positions | **Specified here** |
| Moons, asteroid belts, stations | Planned; paths and RNG streams reserved, not generated yet |
| Planet surfaces: cube-sphere, seamless regions | Constraints decided, details open |
| Generated entities (NPC ships, creatures, loot) | Open |

---

## Determinism rules

These apply to every generator, at every version.

1. **Seeds are derived, never global.** Every RNG is an explicit `random.Random(seed)`.
   ```python
   def derive_seed(world_seed: int, path: str, stream: str) -> int:
       digest = hashlib.blake2b(f"{world_seed}:{path}:{stream}".encode(), digest_size=8).digest()
       return int.from_bytes(digest, "big")
   ```
   Never use Python's `hash()`: it is salted per process.
2. **One RNG stream per aspect.** Each generator uses separately named streams
   (e.g. `cluster_centres`, `star_positions`, `links`, `names`, `planets`). Changing how one
   aspect consumes randomness then doesn't reshuffle the others. The generator version is
   *not* mixed into the seed: a version bump changes logic, not the dice.
3. **Restricted math.** Generator math uses only `+ - * /`, comparisons, `math.sqrt`
   (IEEE-754 correctly rounded) and the `random.Random` methods `random`, `randrange`,
   `randint`, `uniform`, `choices`, `shuffle`. **Forbidden:** `gauss`, `normalvariate`,
   `sin`, `cos`, `log`, `exp`, `pow` with non-integer exponents. libm results for these can
   differ in the last bit between platforms, and that can flip a later rounding or comparison.
   Fourth roots are computed as `sqrt(sqrt(x))`.
4. **Quantized outputs.** Every value a generator outputs is an `int` in fixed units:
   galaxy units, milli-AU, kelvin, milli-L☉ (milli solar luminosity), km, milli-g. Floats
   exist only inside a generation step and are rounded with `round()` before being stored in
   an output or used for a later decision.
5. **Stable iteration order.** No iteration over sets or unordered dicts in generator logic.
   Ties are always broken by index.
6. **Generate-and-validate.** A generator checks its own invariants. If one fails, it
   retries with the stream suffix `/attempt/<n>` (n = 1…10). This is still fully
   deterministic. If all attempts fail, it raises: that is a content/parameter bug, caught by
   tests.

### Object paths and catalog codes
The object path is the stable identity of a generated object. Deltas, pins and the protocol
reference objects by path.

| Object | Path | Catalog code (UI/debug) |
|---|---|---|
| Galaxy | `galaxy` | — |
| Cluster *i* | `c/<i>` | `C3` |
| Star system *s* | `s/<s>` | `S017` |
| Planet *p* of system *s* | `s/<s>/p/<p>` | `S017-P2` |
| Reserved: moon, belt, station | `s/<s>/p/<p>/m/<m>`, `s/<s>/b/<b>`, `s/<s>/st/<n>` | — |
| Reserved: surface region | `s/<s>/p/<p>/r/<face>/<u>/<v>` | — |

Star indices *s* are global (0…99). Planet indices *p* are 1-based in orbit order
(innermost = 1).

---

## Coordinates and the star chart

- **Galaxy plane:** 2D, integer **galaxy units (gu)**, origin at the galaxy centre, x to the
  right and y down (screen convention). The galaxy is the ellipse `x²/a² + y²/b² ≤ 1`.
- **System plane:** 2D, integer **milli-AU**, origin at the star.
- Distances and positions are for visualisation and travel-time calculation. Movement
  between systems happens **only along links**; the link graph is the real topology.

The client presents a **three-level star chart**:

| View | Shows | Data needed |
|---|---|---|
| Galaxy | Cluster blobs (centre, radius, name), bridges between clusters, optionally stars as dots | clusters, bridge edges, star positions |
| Cluster | Stars of one cluster with names/class colour, lanes inside the cluster, bridge endpoints as exits to neighbouring clusters | stars of the cluster, lanes, bridges touching it |
| System | The star at the centre, planets on static orbit rings | system record (star + planets) |

---

## Galaxy generation

Generator `galaxy`, root object `galaxy`. Output: clusters, stars (position, cluster,
index, name), links.

### Parameters — `content/worldgen/galaxy.toml`
```toml
star_count = 100
semi_axis_a = 1000            # gu, horizontal
semi_axis_b = 600             # gu, vertical
edge_margin = 0.85            # cluster centres stay inside the ellipse scaled by this factor

cluster_count = [6, 8]        # inclusive range, rolled
min_stars_per_cluster = 8
cluster_size_weights = [1, 1, 2, 2, 3]   # relative size weights, rolled per cluster
radius_per_sqrt_star = 22     # gu; cluster radius = this × sqrt(star count) × jitter
radius_jitter = [0.85, 1.15]
void_gap = 100                # gu, minimum empty space between cluster discs
centre_bias = 0.6             # 0 = uniform disc, 1 = strongly centre-heavy
min_star_separation = 25      # gu
max_placement_attempts = 500  # per cluster centre / per star

[links]
k_nearest = 3
p_extra = 0.35                # chance to add each candidate non-MST lane
max_degree = 5
max_lane_length = 2.0         # × the cluster's radius
extra_bridge_ratio = 0.3      # extra cluster pairs = round(cluster_count × ratio)
bridge_candidates = 3         # choose a bridge among the N closest star pairs
max_bridges_per_cluster = 3
```

### Step 1 — cluster sizes and radii (stream `cluster_sizes`)
1. Roll `cluster_count`, then a size weight per cluster from `cluster_size_weights`.
2. Each cluster gets `min_stars_per_cluster`. The remaining
   `star_count − cluster_count × min` stars are dealt one at a time to a cluster chosen
   with `rng.choices` weighted by the size weights. Content check: `star_count ≥
   max(cluster_count) × min_stars_per_cluster`.
3. Radius `r_i = round(radius_per_sqrt_star × sqrt(n_i) × uniform(radius_jitter))`. The
   radius grows with the star count, so a cluster's area always leaves room for its stars
   at `min_star_separation` (≈ 55 gu for 8 stars, ≈ 110 gu for 25).

### Step 2 — cluster centres (stream `cluster_centres`)
1. Place centres one by one, largest cluster first, by rejection sampling: draw `(x, y)`
   uniformly in the bounding box of the ellipse scaled by `edge_margin`. Accept if the
   point is inside that ellipse and `dist(centre_i, centre_j) ≥ r_i + r_j + void_gap` for
   all placed clusters.
2. If a centre can't be placed within `max_placement_attempts`, the step fails →
   generate-and-validate retry.
3. Quantize centres to integer gu.

### Step 3 — star positions (stream `star_positions`)
For each cluster, in cluster order, place its stars:
1. Draw a point uniformly in the unit disc by rejection (`u, v ∈ [−1, 1]`, accept if
   `u² + v² ≤ 1`).
2. Centre bias without `gauss`: accept the point with probability
   `1 − centre_bias × (u² + v²)` (otherwise redraw). Clusters are denser at the core.
3. Position = `centre + r_i × (u, v)`, rounded to integer gu.
4. Reject if outside the full galaxy ellipse or closer than `min_star_separation` to any
   star already placed (in any cluster).
5. If a cluster can't fit its stars within `max_placement_attempts` per star, the galaxy
   step fails → generate-and-validate retry.

### Step 4 — ordering, indices, names
- Clusters are ordered by centre `(x, y)` → cluster index `i`.
- Stars are ordered by `(cluster index, x, y)` → global star index `s` (0…99).
- Names are assigned (see [Names](#names)).

### Link generation (stream `links`)
Links are undirected edges `{a, b, length, kind}`, with `a < b` (star indices),
`length` = rounded Euclidean distance in gu, and `kind` ∈ `lane` | `bridge`. Travel time
along a link is computed by the sim from `length` and ship stats; world-gen doesn't
define it.

**Crossing test.** Two segments cross if they intersect at a point that is not a shared
endpoint. Use the exact integer orientation test (cross products on integer coordinates),
with no floats. No accepted link may cross another.

Order of construction:
1. **Intra-cluster spanning lanes.** For each cluster, build the Euclidean minimum
   spanning tree (Prim, O(n²); ties broken by star index). Every edge becomes a `lane`.
   (A Euclidean MST is always planar.)
2. **Spanning bridges.** Build a complete graph over clusters. The weight of a cluster
   pair is the distance between its closest pair of stars. Take its MST. For each MST
   pair, in increasing weight order, list the `bridge_candidates` closest star pairs
   between the two clusters. Pick one with `rng` among those that don't cross an existing
   link and don't exceed `max_degree`. If none qualify, try the next closest pairs; if
   still none, fail → retry.
3. **Extra bridges.** `round(cluster_count × extra_bridge_ratio)` additional cluster pairs,
   chosen from the non-MST pairs weighted toward shorter pairs (weight `1 / rank`). Each
   is added like step 2 but skipped (not failed) if it would cross, break `max_degree`,
   or push either cluster past `max_bridges_per_cluster`. At most one bridge per cluster
   pair.
4. **Extra intra-cluster lanes.** For each star in index order, for each of its
   `k_nearest` same-cluster neighbours not already linked: with probability `p_extra`,
   add a `lane` if it doesn't cross, both ends stay ≤ `max_degree`, and
   `length ≤ max_lane_length × r_cluster`.

### Galaxy invariants (each is a test)
- Exactly `star_count` stars; every star inside the ellipse; pairwise distance ≥
  `min_star_separation`.
- Cluster discs (centre, `r_i`) are separated by ≥ `void_gap`.
- The link graph is connected; every star has degree 1…`max_degree`.
- Each cluster's lanes alone connect that cluster.
- Bridges join different clusters; ≤ 1 bridge per cluster pair; ≤
  `max_bridges_per_cluster` per cluster; the cluster graph induced by bridges is connected.
- No two links cross.
- Same `world_seed` → byte-identical canonical output (golden-hash test).

---

## Star systems

Generator `system`, root object `s/<s>`. Input: `world_seed`, star index, and the star's
galaxy record (needed only for the name). Output: the star record + its planets. Streams:
`star`, `planets`, `planet/<p>`.

### Stars — `content/worldgen/stars.toml`
Main sequence only (O B A F G K M). Weights are gameplay-tuned, not astronomical
(real-life M dwarfs are ~75% of stars).

| Class | Weight | Temp (K) | Luminosity (L☉) | Radius (R☉) | Colour | Planet count 0…8 weights |
|---|---|---|---|---|---|---|
| O | 1 | 30 000–45 000 | 20 000–100 000 | 6.6–15 | blue | 3 3 2 2 1 1 0 0 0 |
| B | 2 | 10 000–30 000 | 25–20 000 | 1.8–6.6 | blue-white | 2 2 2 2 2 1 1 0 0 |
| A | 6 | 7 500–10 000 | 5–25 | 1.4–1.8 | white | 1 1 2 2 2 2 1 1 0 |
| F | 14 | 6 000–7 500 | 1.5–5 | 1.15–1.4 | yellow-white | 1 1 1 2 2 2 2 1 1 |
| G | 22 | 5 200–6 000 | 0.6–1.5 | 0.9–1.15 | yellow | 1 1 1 2 2 3 2 2 1 |
| K | 30 | 3 700–5 200 | 0.08–0.6 | 0.7–0.9 | orange | 1 1 2 2 2 2 1 1 0 |
| M | 25 | 2 400–3 700 | 0.001–0.08 | 0.1–0.7 | red | 2 2 2 2 1 1 0 0 0 |

Generation (stream `star`):
1. Class by weighted choice. **Subclass** `0…9` uniform (0 = hottest, as in "G2").
2. Position within the class: `t = (9 − subclass + rng.random()) / 10` ∈ [0, 1), where
   1 is the hot end.
3. Temperature and radius: linear interpolation `low + t × (high − low)`.
4. Luminosity spans orders of magnitude, so it is interpolated in fourth-root space:
   `q = low^¼ + t × (high^¼ − low^¼)`, `L = q⁴`. (The `^¼` of the table bounds is computed as
   `sqrt(sqrt(x))`.)
5. Stored: `class`, `subclass`, `temperature_k`, `luminosity_mlsun` (milli-L☉),
   `radius_milli_rsun`, `colour` (content key for sprite tint).

Derived values (computed when needed, not stored):
- Habitable zone: inner `sqrt(L / 1.1)` AU, outer `sqrt(L / 0.53)` AU.
- Frost line: `4.85 × sqrt(L)` AU.

### Planet slots and orbits (stream `planets`)
1. Planet count from the class's 0…8 weights. Systems with 0 planets are valid (waypoints).
2. First orbit: `d₁ = sqrt(L) × uniform(first_orbit_factor)`, default `[0.15, 0.8]` AU.
   Since equilibrium temperature scales with `L^¼ / sqrt(d)`, scaling orbits by `sqrt(L)`
   gives every star class a comparable spread of planet temperatures. The star class
   instead shows in planet count, colour, and resource modifiers.
3. Each next orbit: `dₙ = dₙ₋₁ × uniform(orbit_ratio)`, default `[1.4, 2.2]`
   (a Titius–Bode-like spacing).
4. Orbits are stored as integer milli-AU.
5. **Static position** on the orbit ring: draw a unit-disc point by rejection with
   `0.01 ≤ u² + v² ≤ 1`, normalize by `sqrt(u² + v²)`, and multiply by the orbit radius.
   Round to integer milli-AU. No trigonometry. Positions never change over time.

Parameters live in `content/worldgen/planets.toml` (`first_orbit_factor`,
`orbit_ratio`, size classes, temperature buckets, planet types).

### Planet physical properties (stream `planet/<p>`)
1. **Equilibrium temperature** (fixed classification albedo 0.3):
   `T = 278 × 0.915 × L^¼ / sqrt(d_AU)`, with `0.915 ≈ (1 − 0.3)^¼` as a constant.
   Stored as integer kelvin.
2. **Temperature bucket** (content): scorched ≥ 600 K, hot 350–599, temperate 240–349,
   cold 120–239, frozen < 120.
3. **Size class** by weighted choice; weights depend on whether `d` is inside or beyond
   the frost line:

   | Size class | Radius (km) | Weight inside frost line | Weight beyond | Surface N |
   |---|---|---|---|---|
   | tiny | 1 000–2 500 | 20 | 10 | 1 |
   | small | 2 500–4 500 | 30 | 15 | 2 |
   | medium | 4 500–7 500 | 30 | 15 | 3 |
   | large | 7 500–12 000 | 15 | 15 | 4 |
   | giant | 20 000–70 000 | 5 | 45 | — |

   Radius is rolled uniformly within the class range.
4. **Planet type**: filter `planet_types` to those whose temperature range contains `T` and
   whose allowed sizes contain the size class, then pick by weight.
5. **Gravity** (milli-g): `round(1000 × radius_km / 6371 × density_factor)`, with
   `density_factor` from the type.
6. **Habitable-zone flag**: `d` lies within the star's habitable zone (display/flavour).

### Planet types — `content/worldgen/planets.toml`
Example starting table (all values tunable):

| Type | Temp (K) | Sizes | Weight | Atmosphere | Landable | Density factor |
|---|---|---|---|---|---|---|
| lava | ≥ 600 | tiny–large | 10 | thin | yes | 1.1 |
| toxic | 350–800 | medium–large | 6 | dense | yes | 0.95 |
| desert | 300–600 | small–large | 8 | thin | yes | 0.9 |
| terran | 240–330 | small–large | 4 | breathable | yes | 1.0 |
| ocean | 260–350 | medium–large | 4 | breathable | yes | 0.9 |
| barren | any | tiny–large | 10 (large: 3) | none | yes | 0.8 |
| ice | < 250 | tiny–large | 10 | thin | yes | 0.6 |
| gas_giant | any | giant | 10 | dense | **no** | 0.25 |
| ice_giant | < 150 | giant | 8 | dense | **no** | 0.3 |

Each type also has an i18n name key (`planet_type.lava.name`), a sprite key, a
`resource_profile`, and (later) a biome set for surface-gen.

**Coverage validation (startup):** for every (temperature bucket × size class)
combination, at least one type must qualify. Otherwise content loading fails. This
guarantees step 4 never has an empty candidate list.

### Resources — `content/worldgen/resources.toml`
Planets get **abundance profiles** per resource **category**, not concrete items. Economy
maps item IDs to categories later (see [economy](economy.md)).

- Categories: `metals`, `rare_metals`, `crystals`, `volatiles`, `gas`, `organics`,
  `radioactives`, `exotic`.
- Each planet type's `resource_profile` gives an abundance range `[min, max]` (0–100) per
  category. Missing categories mean 0. Example: `lava = { metals = [40, 80],
  rare_metals = [10, 40], radioactives = [20, 50] }`.
- Optional star-class modifiers (additive, clamped to 0–100), e.g. O/B stars `+10
  exotic`, `+10 radioactives`; M stars `−5 rare_metals`.
- Each category rolls uniformly in its range (stream `planet/<p>/resources`, categories in
  fixed listed order), and the result is stored as an int 0–100.
- Gas and ice giants: `gas` / `volatiles` are harvestable from orbit. Rocky planets'
  abundances drive concrete deposit placement in surface-gen (later).

### Planet output record
| Field | Type | Notes |
|---|---|---|
| `path` | str | `s/<s>/p/<p>` |
| `index` | int | 1-based orbit order |
| `orbit_mau` | int | milli-AU |
| `pos_mau` | (int, int) | static position in the system plane |
| `temperature_k` | int | equilibrium temperature |
| `temp_bucket` | str | content key |
| `size_class` | str | content key |
| `radius_km` | int | |
| `gravity_mg` | int | milli-g |
| `type` | str | content key |
| `atmosphere` | str | from type |
| `landable` | bool | from type; giants never |
| `surface_n` | int \| null | cube-sphere face resolution; null if not landable |
| `in_habitable_zone` | bool | |
| `resources` | dict[str, int] | category → abundance 0–100 |
| `name` | str | resolved at read time (see Names) |

---

## Names

- **Star names** come from a name pool in `content/worldgen/names.toml`
  (`star_names = ["Avior", "Kessar", …]`). The galaxy generator copies the pool, sorts it
  (input order must not matter), shuffles it with stream `names`, and assigns names in star
  index order. **Cluster names** work the same way from `cluster_names`.
- Validation: the pool has no duplicates and contains ≥ `star_count` names (≥ cluster count
  for clusters).
- Star and cluster names are **proper nouns stored as literal strings**, not i18n keys,
  and are not translated. Planet *types* and other descriptive text still use i18n keys.
- **Planet names** default to `<Star name> <Roman numeral of index>` (e.g. "Avior III"),
  formatted at read time, not stored.
- **Custom planet names (delta):** table `body_names(object_path PK, custom_name,
  updated_at)`. If a row exists, it overrides the default name. A custom name is a delta,
  so it pins the planet's system (see below). There is currently **no API** to set it;
  rows are written directly in the DB. A rename feature (who may rename, validation,
  moderation) comes later.

---

## Versioning and deltas (per-object pinning)

Each generator has an integer version and a registry of implementations:

```python
GENERATORS = {
    "galaxy": {1: galaxy_v1.generate},
    "system": {1: system_v1.generate},
    # "surface": {...}  later
}
LATEST = {"galaxy": 1, "system": 1}
```

Old versions stay in code (`server/app/world/<generator>/v<N>.py`) as long as anything
uses them.

### Rules
- **Generator root objects:** `galaxy` → `galaxy`; `system` → `s/<s>`; `surface` (later) →
  `s/<s>/p/<p>`.
- **Galaxy is always pinned.** The world row stores its galaxy version
  (`worlds(world_id, seed, galaxy_version, created_at)`), and the live galaxy never
  silently regenerates. Galaxy changes for the live world must be **additive** (e.g. a
  future expansion generator that adds clusters without moving existing stars), or happen
  in a new world.
- **Other generators pin per object.** Table `worldgen_pins(object_path, generator,
  version, pinned_at)`, primary key `(object_path, generator)`.
  - An object with no pin is generated with `LATEST[generator]`.
  - When the **first delta** touching an object is written, a pin to the current latest
    version is inserted **in the same transaction** for every generator root on its
    ancestor path. Example: a custom name on `s/17/p/2` pins `system` for `s/17`. A future
    building in a region of `s/17/p/2` pins `surface` for `s/17/p/2` *and* `system` for
    `s/17`.
  - Pinned objects keep their version even after newer versions ship. Untouched objects
    pick up improvements automatically.
- **Startup check:** every `(generator, version)` that appears in `worldgen_pins`
  must exist in `GENERATORS`; otherwise the server refuses to start.
- **Golden-hash tests:** for each `(generator, version)`, a test generates fixed seeds,
  serializes the output canonically (sorted-key JSON), and compares its SHA-256 with a
  stored hash. Changing a generator's output without bumping its version fails CI.
- Every version bump adds an entry to the [log](#generator-version-log): what changed and
  whether old versions can be retired.

### Caching
Generation is cheap but not free. The server keeps an in-memory LRU of generated system
records keyed by `(path, version)`. The galaxy is generated once at startup and held for
the process lifetime.

---

## Delivery to the client

Proposed (to be finalized in [protocol](protocol.md)):
- `GET /api/world/galaxy` — clusters, stars (index, name, class, position, cluster),
  links. It is static for the world, so it is served with an `ETag` derived from
  `(galaxy_version, output hash)` and cached by the client.
- `GET /api/world/systems/{s}` — the star + planets record, with custom names resolved.
- Live changes (e.g. a renamed planet) arrive as WebSocket deltas for subscribed areas.

---

## Planet surfaces (outline)

Decided:
- Only landable planets have surfaces; **gas and ice giants are not landable**.
- Topology is a **cube-sphere**: 6 faces, each split into `N × N` **regions**, with `N`
  from the size class (tiny 1 → 6 regions … large 4 → 96 regions).
- Regions are **seamless**: a player can walk from region A into a neighbouring region B,
  including across cube-face edges (cube adjacency table).
- Seamlessness comes from sampling **one planet-global field**. Every tile maps to a point
  on the unit sphere (cube point normalized with `sqrt`, no trig), and terrain/biome noise
  is sampled at that 3D point. Neighbouring tiles therefore agree regardless of which
  region or face they belong to.
- Region tile maps are generated lazily when entered (generator `surface`, root
  `s/<s>/p/<p>`).

Open: tiles per region, biome set per planet type, deposit placement from abundances,
points of interest, how regions are used as ground-combat boards.

## Generated entities (outline)
Moons, asteroid belts, stations, NPC ships, creatures, loot. Their paths are reserved in
[Object paths](#object-paths-and-catalog-codes). Each will get its own RNG streams under
its parent so adding it later doesn't disturb existing output. Decisions are open.

---

## Module layout

```
server/app/world/
  seeds.py        derive_seed, rng(world_seed, path, stream)
  geometry.py     integer geometry: distance², segment crossing, ellipse containment
  galaxy/v1.py    clusters, star placement, ordering, names → GalaxyV1
  links.py        MST (Prim), bridges, extra lanes (used by galaxy/v1)
  system/v1.py    star + planets → SystemV1
  naming.py       name-pool assignment, Roman numerals, display-name resolution
  versions.py     GENERATORS / LATEST registry
  types.py        frozen dataclasses for outputs (Cluster, Star, Link, Planet, …)
content/worldgen/
  galaxy.toml  stars.toml  planets.toml  resources.toml  names.toml
```
Pydantic schemas validate the five TOML files at startup, including the cross-file checks
above (pool sizes, planet-type coverage, resource categories exist). Tests mirror this
layout under `server/tests/world/`.

---

## Open questions
- Fog of war / discovery: does a player see the whole chart, or only explored systems?
- Are cluster names shown to players, or used only internally?
- Travel-time model along lanes vs bridges (sim; e.g. bridges slower or hazardous?).
- Galaxy growth beyond 100 stars: design of the additive expansion generator.
- Unpinning: may an object be unpinned once all its deltas are gone?
- Surface details (see outline above).

## Generator version log
_(none yet — `galaxy` v1 and `system` v1 will be the first entries when implemented)_
