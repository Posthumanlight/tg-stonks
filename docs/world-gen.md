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
- **One persistent galaxy**: the live server has a single world with a single `world_seed`,
  configured as the `WORLD_SEED` env var (see [World seed](#world-seed)).
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
   (e.g. `cluster_centres`, `star_positions`, `links`, `names`, `slots`). Changing how one
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
radius_per_sqrt_star = 26     # gu; cluster radius = this × sqrt(star count) × jitter
radius_jitter = [0.85, 1.15]
void_gap = 100                # gu, minimum empty space between cluster discs
centre_bias = 0.6             # 0 = uniform disc, 1 = strongly centre-heavy
min_star_separation = 25      # gu
max_placement_attempts = 500  # per cluster centre / per star
max_generation_attempts = 10  # generate-and-validate retries

[links]
k_nearest = 3
p_extra = 0.35                # chance to add each candidate non-MST lane
max_degree = 5
max_lane_length = 2.0         # × the cluster's radius
extra_bridge_ratio = 0.3      # extra cluster pairs = round(cluster_count × ratio)
bridge_candidates = 3         # choose a bridge among the N closest star pairs
max_bridges_per_cluster = 3
bridge_clearance = 1.0        # bridges keep >= this × radius away from other clusters' centres
```
With these defaults, 183 of 200 test seeds succeed on the first attempt and all within 3.
Generation takes about 40 ms.

### Step 1 — cluster sizes and radii (stream `cluster_sizes`)
1. Roll `cluster_count`, then a size weight per cluster from `cluster_size_weights`.
2. Each cluster gets `min_stars_per_cluster`. The remaining
   `star_count − cluster_count × min` stars are dealt one at a time to a cluster chosen
   with `rng.choices` weighted by the size weights. Content check: `star_count ≥
   max(cluster_count) × min_stars_per_cluster`.
3. Radius `r_i = round(radius_per_sqrt_star × sqrt(n_i) × uniform(radius_jitter))`. The
   radius grows with the star count, so a cluster's area always leaves room for its stars
   at `min_star_separation` (≈ 74 gu for 8 stars, ≈ 130 gu for 25).

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
   between the two clusters. Pick one with `rng` among those that qualify: no crossing
   with an existing link, no star exceeding `max_degree`, and **clearance**: the bridge
   passes at least `bridge_clearance × r_k` from the centre of every third cluster *k*,
   so it runs through the void rather than through another cluster. If none qualify, try
   the next closest pairs. If still none, fail → retry.
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

A system is produced by two generators, versioned and pinned separately (see
[Versioning](#versioning-and-deltas-per-object-pinning)):

| Generator | Root object | Input | Output | Streams |
|---|---|---|---|---|
| `system` (skeleton) | `s/<s>` | `world_seed`, star index | star properties + planet slots (orbit, static position) | `star`, `slots` |
| `planet` | `s/<s>/p/<p>` | `world_seed`, the system skeleton, planet index | physical properties, type, resources | `planet`, `resources` |

The skeleton is the planet's **structural context**: a planet's temperature depends on the
star's luminosity and its own orbit. Names are not part of either output; they're resolved
at read time (see [Names](#names)).

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

### Planet slots and orbits (generator `system`, stream `slots`)
1. Planet count from the class's 0…8 weights. Systems with 0 planets are valid (waypoints).
2. First orbit: `d₁ = sqrt(L) × uniform(first_orbit_factor)`, default `[0.08, 0.7]` AU.
   With `L` taken from the quantized `luminosity_mlsun`, the first planet lands
   between ≈ 300 K and ≈ 900 K.
   Since equilibrium temperature scales with `L^¼ / sqrt(d)`, scaling orbits by `sqrt(L)`
   gives every star class a comparable spread of planet temperatures. The star class
   instead shows in planet count, colour, and resource modifiers.
3. Each next orbit: `dₙ = dₙ₋₁ × uniform(orbit_ratio)`, default `[1.4, 2.2]`
   (a Titius–Bode-like spacing).
4. Orbits are stored as integer milli-AU. Each orbit is computed from the previous
   *rounded* orbit and is forced to be at least 1 mAU further out.
5. **Static position** on the orbit ring: draw a unit-disc point by rejection with
   `0.01 ≤ u² + v² ≤ 1`, normalize by `sqrt(u² + v²)`, and multiply by the orbit radius.
   Round to integer milli-AU. No trigonometry. Positions never change over time.

Parameters live in `content/worldgen/planets.toml` (`first_orbit_factor`,
`orbit_ratio`, size classes, temperature buckets, planet types).

### Planet physical properties (generator `planet`, stream `planet`)
1. **Equilibrium temperature** (classification albedo from content, default 0.3):
   `T = 278 × (1 − albedo)^¼ × L^¼ / sqrt(d_AU)`, with every `^¼` computed as
   `sqrt(sqrt(x))` (`(1 − 0.3)^¼ ≈ 0.915`). Stored as integer kelvin.
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
| barren | any | tiny–large | 6 (large: 2) | none | yes | 0.8 |
| ice | < 250 | tiny–large | 10 | thin | yes | 0.6 |
| gas_giant | any | giant | 10 | dense | **no** | 0.25 |
| ice_giant | < 150 | giant | 8 | dense | **no** | 0.3 |

Temperature ranges are half-open `[min_k, max_k)`; an omitted bound is unbounded. Each type
also has an i18n name key (`planet_type.lava.name`), a sprite key, a `resources` profile,
optional per-size weight overrides (`size_weights`), and (later) a biome set for
surface-gen.

Resulting mix over 3 000 generated systems: barren 37%, ice 25%, desert 15%, gas giant 7%,
terran 5%, toxic 4%, lava 3%, ocean 2%, ice giant 2%. Barren dominates because it's the
only type for small rocks in several temperature ranges; tune in `planets.toml`.

**Coverage validation (startup):** for every size class, the temperature ranges of the
types allowing it (with weight > 0) must together cover all of `[0, ∞)`. Otherwise content
loading fails. This guarantees step 4 never has an empty candidate list. Startup
validation also checks that landable types only use size classes with a `surface_n`, and
that every resource category referenced exists.

### Resources — `content/worldgen/resources.toml`
Planets get **abundance profiles** per resource **category**, not concrete items. Economy
maps item IDs to categories later (see [economy](economy.md)).

- Categories: `metals`, `rare_metals`, `crystals`, `volatiles`, `gas`, `organics`,
  `radioactives`, `exotic`.
- Each planet type's `resources` table gives an abundance range `[min, max]` (0–100) per
  category. Missing categories mean 0. Example: `lava = { metals = [40, 80],
  rare_metals = [10, 40], radioactives = [20, 50] }`.
- Optional star-class `resource_modifiers` (additive, clamped to 0–100), e.g. O stars
  `+15 exotic`, `+10 radioactives`; M stars `−5 rare_metals`. Modifiers apply only to
  categories the planet type has; a missing category stays 0.
- Each category rolls uniformly in its range (generator `planet`, stream `resources`,
  categories in `resources.toml` order), and the result is stored as an int 0–100. Append
  new categories at the end of that file.
- Gas and ice giants: `gas` / `volatiles` are harvestable from orbit. Rocky planets'
  abundances drive concrete deposit placement in surface-gen (later).

### Planet output record
| Field | Type | Notes |
|---|---|---|
| `version` | int | `planet` generator version that produced it |
| `path` | str | `s/<s>/p/<p>` |
| `code` | str | `S017-P2` |
| `index` | int | 1-based orbit order |
| `orbit_mau` | int | milli-AU (from the skeleton slot) |
| `x_mau`, `y_mau` | int | static position in the system plane (from the slot) |
| `temperature_k` | int | equilibrium temperature |
| `temp_bucket` | str | content key |
| `size_class` | str | content key |
| `radius_km` | int | |
| `gravity_mg` | int | milli-g |
| `planet_type` | str | content key |
| `atmosphere` | str | from type |
| `landable` | bool | from type; giants never |
| `surface_n` | int \| null | cube-sphere face resolution; null if not landable |
| `in_habitable_zone` | bool | |
| `resources` | dict[str, int] | category → abundance 0–100 |


The display name is not part of the record; it is resolved at read time (see Names).

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
  so it pins the planet (and, as structural context, its system skeleton; see below).
  There is currently **no API** to set it. Rows are written directly in the DB, or with
  `worldgen_repo.set_body_name()` from a script. Rows written by hand get their pins from
  `reconcile_body_name_pins()`, which is meant to run at server startup. A rename feature
  (who may rename, validation, moderation) comes later.

---

## Versioning and deltas (per-object pinning)

Each generator has an integer version and a registry of implementations:

```python
# server/app/world/versions.py
GENERATORS = {
    "galaxy": {1: galaxy_v1.generate},
    "system": {1: system_v1.generate},   # skeleton: star + planet slots
    "planet": {1: planet_v1.generate},
    # "surface": {...}  later
}
LATEST = {name: max(vs) for name, vs in GENERATORS.items()}
DEPENDENCIES = {"galaxy": (), "system": (), "planet": ("system",)}
```

Old versions stay in code (`server/app/world/<generator>/v<N>.py`) as long as any pin
references them.

### Rules
- **Generator root objects:** `galaxy` → `galaxy`; `system` → `s/<s>`; `planet` →
  `s/<s>/p/<p>`; later `surface` → `s/<s>/p/<p>`, moons, belts and stations → their own
  paths.
- **Galaxy is always pinned.** The world row stores its galaxy version
  (`worlds(world_id, seed, galaxy_version, created_at)`), and the live galaxy never
  silently regenerates. Galaxy changes for the live world must be **additive** (e.g. a
  future expansion generator that adds clusters without moving existing stars), or happen
  in a new world.
- **A delta locks only the entity it touches**, plus that entity's **structural
  context**. Table `worldgen_pins(object_path, generator, version, pinned_at)`, primary key
  `(object_path, generator)`.
  - An object with no pin is generated with `LATEST[generator]`.
  - When the **first delta** touching an entity is written, pins to the current latest
    versions are inserted **in the same transaction** for the entity's own generator *and*
    each generator in its `DEPENDENCIES`, on the matching ancestor object
    (`versions.pins_for_delta`, `worldgen_repo.pin_for_delta`).
  - Example: a custom name on planet `s/17/p/2` pins `("s/17/p/2", "planet")` and
    `("s/17", "system")`. The skeleton is pinned because the planet's inputs (star
    luminosity, its orbit) come from it, so a newer skeleton version can't shift them.
    **Sibling planets stay unpinned** and pick up newer `planet` versions; they share the
    frozen skeleton but not the planet logic.
  - A later moon/station/surface generator declares its dependencies the same way. For
    example, `surface` would depend on `planet` and `system`.
  - Pinned objects keep their version even after newer versions ship. Untouched objects
    pick up improvements automatically.
- **Startup check:** every `(generator, version)` that appears in `worldgen_pins`
  must exist in `GENERATORS` (`worldgen_repo.verify_pins`); otherwise the server refuses
  to start.
- **Golden-hash tests** (`server/tests/world/test_golden.py`): for each
  `(generator, version)`, fixed seeds are generated, serialized canonically (sorted-key
  JSON) and compared by SHA-256 with a stored hash. Changing a generator's output without
  bumping its version fails CI.
- Every version bump adds an entry to the [log](#generator-version-log): what changed and
  whether old versions can be retired.

### Content and versions
World-gen content (`content/worldgen/*.toml`) is an input to every generator, so tuning
it changes output exactly like a code change, golden hashes included. **Until launch**,
tune freely and update the golden hashes. **After launch** this needs a rule (open
question): either freeze worldgen content per generator version (a tuning change becomes
a version bump that ships its own copy of the tables), or accept that tuning also changes
pinned objects.

### World seed
- `WORLD_SEED` env var (integer `0 … 2^63 − 1`, so it fits a signed BIGINT), read via
  `Settings.require_world_seed()`.
- On first start, `worldgen_repo.ensure_world()` creates the `worlds` row with the seed and
  the latest galaxy version. On later starts it **refuses to start** if `WORLD_SEED`
  differs from the stored seed, which protects against silently generating a different
  galaxy under existing deltas.

### Caching
Generation is cheap but not free. `WorldGenerator` (`server/app/world/generator.py`)
keeps an in-memory LRU of system skeletons and planets keyed by index and version. The
galaxy is generated once and held for the process lifetime. Version resolution needs pins
from the DB, so callers pass versions in; `None` means unpinned (latest).

### Debug snapshot (`gen_*` tables)
To browse the generated world in a DB UI (e.g. the Supabase table editor), run
`poetry run python server/app/cli/snapshot_world.py`. It generates every cluster, star,
link and planet (respecting pins and custom names) and **replaces** the contents of
`gen_snapshot`, `gen_clusters`, `gen_stars`, `gen_links`, `gen_planets` and
`gen_planet_resources`. This is not an exception to "persist only deltas":
- the game never reads these tables. They are a disposable view for humans and can be
  dropped at any time without losing anything;
- taking a snapshot pins nothing, so generator versions stay free to change;
- the tables live on their own `MetaData` (`app/persistence/worldgen_snapshot.py`), are
  created by the script rather than by Alembic, and are excluded from autogenerate in
  `migrations/env.py`.

After a content or generator change, re-run the script to refresh the snapshot.

---

## Delivery to the client

- **Implemented: `GET /api/world/galaxy`** (`server/app/api/world.py`, `GalaxyView`).
  - **Contents:** the ellipse semi-axes; clusters (index, code, name, centre, radius);
    stars (index, code, name, position, cluster, class, subclass, colour); links.
  - **Pins:** star class comes from the `system` generator and honours `system` pins.
  - **Build and caching:** the view is built once at startup. Its `ETag` is the SHA-256 of
    the canonical JSON, and a matching `If-None-Match` gets 304.
  - **Consumer:** the client's star chart ([client](client.md)).
- Proposed: `GET /api/world/systems/{s}`, the star plus planets record with custom names
  resolved.
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
server/app/world/              pure: no DB, network, clock, files or global RNG
  seeds.py        derive_seed, make_rng(world_seed, path, stream, attempt)
  geometry.py     integer geometry: distance², segment crossing, ellipse containment
  paths.py        object paths and catalog codes, path parsing
  links.py        MST (Prim), bridges, extra lanes (used by galaxy/v1)
  galaxy/v1.py    clusters, star placement, ordering, names, links → Galaxy; validate()
  system/v1.py    star + planet slots → SystemSkeleton
  planet/v1.py    one planet's properties, type, resources → Planet
  naming.py       name-pool assignment, Roman numerals, display-name resolution
  versions.py     GENERATORS / LATEST / DEPENDENCIES, pins_for_delta
  generator.py    WorldGenerator facade with caching
  canonical.py    canonical JSON + hash (golden tests, ETags)
  types.py        frozen dataclasses for outputs
server/app/content/worldgen.py Pydantic schemas + loader for content/worldgen/*.toml
server/app/persistence/
  models/world.py     worlds, worldgen_pins, body_names
  worldgen_repo.py    ensure_world, pin_for_delta, verify_pins, set_body_name, …
  worldgen_snapshot.py  debug gen_* tables (not game state; see "Debug snapshot")
content/worldgen/
  galaxy.toml  stars.toml  planets.toml  resources.toml  names.toml
```
Pydantic schemas validate the five TOML files at startup, including the cross-file checks
above (pool sizes, planet-type coverage, resource categories exist). Tests live in
`server/tests/world/` and `server/tests/persistence/test_worldgen_repo.py`.

---

## Open questions
- Fog of war / discovery: does a player see the whole chart, or only explored systems?
- Are cluster names shown to players, or used only internally?
- Travel-time model along lanes vs bridges (sim; e.g. bridges slower or hazardous?).
- Galaxy growth beyond 100 stars: design of the additive expansion generator.
- Unpinning: may an object be unpinned once all its deltas are gone?
- Content tuning after launch (see [Content and versions](#content-and-versions)).
- Startup wiring: no server entry point exists yet. When `app.main` is added, its startup
  must call `app.world_bootstrap.bootstrap_world()` (ensure_world → reconcile names →
  verify pins → commit → generate the galaxy). Until then, run it by hand with
  `poetry run python server/app/cli/init_world.py` (idempotent).
- Surface details (see outline above).

## Generator version log
| Generator | Version | Date | Change |
|---|---|---|---|
| galaxy | 1 | 2026-11-21 | Initial: ellipse, clusters with voids, MST + extra lanes, bridges with clearance |
| system | 1 | 2026-11-21 | Initial: main-sequence star, 0–8 planet slots, Titius–Bode-like orbits, static positions |
| planet | 1 | 2026-11-21 | Initial: equilibrium temperature, size class by frost line, weighted type, resource abundances |
