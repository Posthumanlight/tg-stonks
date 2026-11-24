# Ground Combat

Turn-based squad combat on planet surfaces. Turn order is per unit (HOMM-style, by Speed),
and units are Warhammer-style multi-model squads. The rules and units are original.

This doc is the implementation spec for `server/app/combat/ground/`. Sections marked
**Decided** are agreed. The [Issues](#issues-raised) section lists the design risks,
each with the mitigation we chose.

---

## Decided

### Principles
- **Instanced state machine.** The world sim spawns a combat. It is a self-contained,
  turn-based state machine (CLAUDE.md rule 7), and the server resolves everything
  (rule 1). Clients send intents, the engine checks them against `legal_actions`, and
  emits events.
- **Pure and seeded** (rules 2–3). The engine does no I/O and reads no clock. All
  randomness comes from one per-combat `random.Random`, and **every roll is logged**.
- **Replay.** A combat record is
  `(setup, seed, content_hash, COMBAT_RULES_VERSION, actions[])`. Replaying the actions
  against the same content and rules version reproduces every event.
- **No floats.** The rules use `int` and `fractions.Fraction`. Rounding happens at
  defined points, as described below.
- **Data-driven and modular** (rule 9).
  - Units, weapons, terrain and damage tables live in `content/combat/`.
  - **Abilities are plain Python functions hooked into events.** The content says *which*
    functions fire on *which* event, and with *which* parameters.
  - A new ability built from existing functions needs only TOML. A new kind of behaviour
    means writing a new function.

### Summary of the core rules
| Topic | Rule |
|---|---|
| Board | Square grid of **variable size, 32×32 by default**; Chebyshev distance |
| Units on board | One token per unit (a stack with a model-count badge); 1×1 or 2×2 footprint |
| Turn order | Each unit acts once per round, in Speed order; Wait sends it to a later queue |
| Standard actions | Move, Wait, Skip. Everything else comes from weapons and abilities |
| Budget | A movement pool of `movement` squares, which can be split, plus `action_points`. Attacking ends movement |
| Attacks | No to-hit roll: every hit lands. Damage per hit is `constant + dice` |
| Damage allocation | Per model, **no spill**: excess damage on a model is lost |
| Armor | `light / heavy / vehicle / monster / character` × weapon type → damage % table |
| LoS | Exact centre-to-centre line. Terrain **and units** can block or screen |
| Cover | Directional (obstacle or screening unit next to the target) or area (standing in it). Halves ranged damage |
| Engagement | Changes nothing about attacking: **any weapon can be used while engaged**. Its only effect is that leaving an enemy's reach provokes an **opportunity attack** (D&D-style) |

---

## Board

- **Grid.** The board is a W×H grid of squares at integer coordinates `(x, y)`, with
  `(0, 0)` at the top-left.
  - The size **varies per battle**: it is set by the map or by combat setup, within
    `rules.board_min` to `rules.board_max`.
  - The **standard board is 32×32** (`rules.default_board`).
  - Later, maps will be generated from planet-surface regions
    ([world-gen](world-gen.md)).
- **Neighbours.** Each square has 8 neighbours. **Distance is Chebyshev**:
  `max(|dx|, |dy|)`, so a diagonal step costs 1, as in D&D. The same metric is used for
  movement, weapon range, reach and ability radii.
- **Footprints.** A unit occupies its footprint (1×1 or 2×2). The distance between two
  units is the smallest distance between any pair of their squares. A unit is
  **adjacent** to another at distance 1.
- **No corner cutting.** A diagonal step is illegal if either of the two orthogonal
  squares it passes between has impassable terrain. Units don't block corners.
- **On a phone.** A 32×32 board at a 44 px tap target is about 1400 px across, so the
  board view always pans and zooms. See [Issue 9](#issues-raised) for the camera rules.

### Terrain — `content/combat/terrain.toml`
Each terrain type sets:
- `passable` (bool);
- `move_cost` (1 = normal, 2 = difficult);
- `blocks_los` (bool);
- `cover`: `none | obstacle | area`.

| Example | passable | move_cost | blocks_los | cover |
|---|---|---|---|---|
| open | ✓ | 1 | – | none |
| rubble | ✓ | 2 | – | area |
| forest | ✓ | 2 | – | area |
| low wall / crates | – | – | – | obstacle |
| wall / rock | – | – | ✓ | – |
| deep water | – | – | – | none |

**Overlays** are temporary terrain layers that abilities place on squares for a number
of rounds, such as `smoke` (blocks LoS) or `fire`. An overlay overrides the fields it
sets. Overlays are defined in the same file under `[overlays.*]`.

### Occupancy
- Units may move **through friendly units** but not end on them.
- **Enemy units block** movement.
- A 2×2 unit needs every square of its footprint to be passable and free.

---

## Units — `content/combat/units.toml`

| Field | Meaning |
|---|---|
| `speed` | Turn order (higher acts first) |
| `movement` | Squares per activation (the movement pool) |
| `hp` | HP **per model** (groups may override it) |
| `armor` | `light / heavy / vehicle / monster / character`. Indexes the damage table |
| `tags` | Unit types (`infantry`, `mechanical`, `beast`, `psychic`, `leader`, …) that abilities check. Validated against `tags.toml` |
| `action_points` | AP per activation |
| `footprint` | `1` (1×1) or `2` (2×2) |
| `models` | `{ min, max }` unit size. Capped by `rules.max_models_per_unit` |
| `los_profile` | `none / screen / block` (see [LoS](#line-of-sight)). Default: `block` for a 2×2 footprint or `vehicle`/`monster` armor, otherwise `screen` |
| `points` | Unit value: used for army building and for deciding fights that hit the round limit |
| `abilities` | Unit abilities: ids, or `{ id, …params }` |
| `name_key` | i18n key |

### Loadout: model groups
A unit's models are split into **groups** that share a role, HP and weapons:

```toml
[units.line_troopers]
name_key = "unit.line_troopers.name"
points = 90
speed = 5
movement = 6
hp = 1
armor = "light"
tags = ["infantry", "human"]
action_points = 2
footprint = 1
models = { min = 5, max = 10 }
abilities = []

[[units.line_troopers.groups]]
role = "trooper"
count = 8
fill = true                 # this group grows or shrinks when the unit size changes
weapons = ["pulse_rifle"]
casualty_priority = 0       # dies first

[[units.line_troopers.groups]]
role = "gunner"
count = 1
weapons = ["rail_lance"]
casualty_priority = 1

[[units.line_troopers.groups]]
role = "sergeant"
count = 1
hp = 2                      # overrides the unit's hp
weapons = ["sidearm", "shock_maul"]
casualty_priority = 2       # dies last
```

Exactly one group has `fill = true`. The total of the group counts must stay within
`models.min..max`.

### Runtime unit state (engine)
- Per group: `alive` (the model count).
- **At most one wounded model**, `wounded: (group, hp_left) | None`. Damage always goes
  to the wounded model first, so only one model can be wounded at a time.
- Statuses (with remaining duration and stacks), and reactions available this round.
- The activation budget: `movement_left`, `ap_left`, the weapons used this activation,
  `has_moved`, `has_attacked`, `has_waited`.

---

## Weapons — `content/combat/weapons.toml`

| Field | Meaning |
|---|---|
| `mode` | `melee` or `ranged` |
| `type` | A weapon type from `weapon_types.toml` (`small_arms`, `heavy`, `anti_tank`, `flamer`, `explosive`, `blade`, `artillery`, …). Indexes the damage table |
| `range` | `[min, max]` in squares. Melee is always reach 1 (abilities can extend it) |
| `hits` | Hits **per model carrying the weapon** |
| `damage` | A dice expression: `"3"`, `"D6"`, `"D3+1"`, `"2D6+2"` |
| `ap_cost` | AP per use (default 1) |
| `abilities` | Weapon abilities: ids, or `{ id, …params }` |
| `name_key` | i18n key |

```toml
[weapons.pulse_rifle]
name_key = "weapon.pulse_rifle.name"
mode = "ranged"
type = "small_arms"
range = [1, 16]
hits = 1
damage = "1"

[weapons.rail_lance]
name_key = "weapon.rail_lance.name"
mode = "ranged"
type = "anti_tank"
range = [2, 20]
hits = 1
damage = "D6+2"
ap_cost = 2
abilities = ["heavy", { id = "anti", armor = "vehicle", percent = 150 }]

[weapons.shock_maul]
name_key = "weapon.shock_maul.name"
mode = "melee"
type = "blade"
range = [1, 1]
hits = 3
damage = "D3"
```

- **Dice grammar:** `[N]D<sides>[+K]`, or a plain integer. It is parsed at startup into
  `Dice(count, sides, const)`.
- **Damage table:** `content/combat/damage_table.toml` sets a percentage for every
  (weapon type, armor) pair. Startup validation requires a complete matrix.

```toml
[damage_table.small_arms]
light = 100
heavy = 50
vehicle = 25
monster = 50
character = 100

[damage_table.anti_tank]
light = 75
heavy = 100
vehicle = 150
monster = 125
character = 100
```

---

## Turn structure

### Rounds
1. **Round start.** Statuses tick down, overlays expire, and reactions reset (to 1,
   unless an ability changes it). `round_started` hooks run.
2. **Main queue.** All living units sorted by **effective Speed**, highest first.
   Effective Speed is base Speed after the `stat_calculating` hooks.
   - Ties: the side that won the seeded roll at combat start goes first, and the tie
     winner alternates every round. Then deployment index.
3. **Activations** run in queue order. A unit that Waits moves to the **wait queue**.
4. **Wait queue.** It runs after the main queue is empty, in **reverse** Speed order (the
   slowest waiting unit acts first), as in HOMM.
5. **Round end.** `round_ended` hooks run, then end conditions are checked.

Units that die leave the queues. Units spawned mid-round join the next round.

### Activation
At the start of a unit's activation:
- `movement_left = movement` (after hooks);
- `ap_left = action_points` (after hooks);
- `activation_started` hooks run.

The unit then takes any sequence of these actions:

| Action | Cost | Rules |
|---|---|---|
| **Move**(path) | path cost from the movement pool | Each step costs the terrain's `move_cost`. Not allowed after an attack, unless the attack kept the movement (`keep_movement()`, e.g. `assault`). Leaving an enemy's reach provokes an opportunity attack |
| **Attack**(weapon, target) | `ap_cost` AP | **Any** weapon, ranged or melee, whether engaged or not. Each weapon fires **once per activation**. A unit with several weapons can split fire by firing each at a different target |
| **Ability**(id, target) | the ability's `ap_cost` | Active abilities, with cooldown and limited uses |
| **Wait** | – | Only as the first action, once per round |
| **Skip** | – | Ends the activation. Leftover movement and AP are lost |

- **Auto-end.** The activation ends automatically when no legal action except Skip is
  left.
- **Timeout.** When the activation timer (`rules.activation_timer_s`) runs out, the engine
  applies an automatic Skip.
- **End hook.** `activation_ended` hooks run at the end.

### End of combat
- A side with no units left loses.
- At `rules.round_limit`, the side with more surviving `points` wins. Within
  `rules.draw_margin_percent`, the result is a draw.
- Objectives (holding squares and so on) are future work.

---

## Attack resolution

Every step raises a hook event (see [Events](#event-catalogue)), so abilities can change
it. The pipeline:

1. **Validate** (`attack_validating`). The attack must pass all of these:
   - the weapon is carried by at least one living model;
   - `ap_left ≥ ap_cost`;
   - the weapon hasn't fired this activation;
   - **range:** `min ≤ distance ≤ max`; melee needs distance 1;
   - **LoS** for ranged attacks.

   Engagement plays no part here. Hooks can relax the checks with `allow_without_los()`
   and `add_range()`, or add new ones with `forbid_attack()`.
2. **Declare** (`attack_declared`). AP is spent, and movement is cleared unless a later
   hook keeps it.
3. **Hits** (`hits_calculating`): `hits = weapon.hits × carriers`, then hooks add to it or
   multiply it. A fractional result is rounded stochastically (step 6).
4. **Pick the victim**, once per hit (`hit_allocating`).
   - Hooks may redirect the hit to another living unit (bodyguard) or prevent it.
   - Otherwise the victim is the target.
   - This happens *before* damage is computed, so a redirected hit uses the **victim's**
     armor and cover. Cover is recomputed from the attacker to the victim.
5. **Damage**, per hit (`damage_calculating`, whose target is the victim):
   ```
   value = (roll(weapon.damage) + flat_bonus)
           × armor_percent / 100            # damage_table[weapon.type][victim.armor]
           × (1/2 if cover and ranged)      # hooks can set cover on or off
           × Π multipliers                  # from hooks, Fractions
   ```
6. **Stochastic rounding.** `damage = floor(value)`, plus 1 with probability
   `frac(value)`, drawn from the combat RNG and logged. The expected damage stays exact:
   cover halves damage *on average*, and a 1-damage weapon against cover has a 50%
   chance to deal 1 (not always 0, not always 1). The result is never below 0.
7. **Apply to a model:**
   - The hit goes to the victim's wounded model if there is one. Otherwise it goes to a
     model from the living group with the lowest `casualty_priority`.
   - **No spill:** damage beyond the model's remaining HP is lost.
   - A model at 0 HP is removed (`model_killed`). If the unit has no models left, it is
     destroyed (`unit_destroyed`). When the original target is destroyed, the remaining
     hits are lost.
8. **Resolve** (`attack_resolved`). Totals are known here: hits, damage and kills.

A whole weapon group fires at one target. All hits are resolved in order, so the log
reads hit by hit for the client to animate.

---

## Line of sight

LoS is checked between **squares**, and units affect it.

1. **Geometry.** Draw a segment from the centre of the observer's square to the centre of
   the target's square. Coordinates are doubled, so every centre is an integer point.
   - A square is **crossed** if the segment passes through its *interior*. A segment that
     only touches a corner or an edge doesn't cross the square. The test uses exact
     integers.
   - The observer's and the target's own footprint squares are never counted.
2. **Blockers.** A crossed square **blocks** LoS if any of these holds:
   - its terrain or overlay has `blocks_los`;
   - it is occupied by a unit with `los_profile = block` (vehicles, monsters, 2×2 units).
3. **Screens.** A crossed square that holds a unit with `los_profile = screen` (1×1
   infantry) **does not block**. It counts as an **obstacle for cover**; see below. With
   `rules.friendly_units_screen = true` (the default), both friendly and enemy units
   screen.
4. **Big units.** Between footprints, LoS exists if any (observer square, target square)
   pair has it. For an attack, the engine uses the pair that is **best for the
   attacker**: LoS without cover first, then shortest. Ties are broken by square order,
   so the result is deterministic.
5. **Hook.** `los_checking` runs after the geometry, with mutable `los` and `cover`
   fields. It is used for stealth, spotters and similar effects. It only runs for units
   that have such an ability, so the common case stays fast.

**Symmetry.** Steps 1–4 are symmetric: A sees B exactly when B sees A. This is a test
invariant. Abilities may deliberately break symmetry in step 5 (for example, a stealth
cloak).

**Profile changes.** `los_profile` can be changed at runtime by statuses (for example,
`smoke_screen` sets `block`, and `prone` sets `none`).

**Performance.** On 32×32, LoS between every pair of units is cheap, but the
targeting previews in `legal_actions` call it a lot. Results are cached per state version.

## Cover

Cover is binary (no stacking), applies only to **ranged** damage, and **halves** it.

- **Area cover.** The target stands in terrain or an overlay with `cover = area`. A 1×1
  unit needs its own square in it; a 2×2 unit needs at least 2 of its 4 squares in it.
- **Directional cover.** On the chosen line of fire, a crossed square that holds an
  **obstacle** (terrain `cover = obstacle`, or a screening unit) is **adjacent to the
  target's footprint**. **Flanking** means choosing a line that avoids such squares.
  - An obstacle that is also adjacent to the *attacker* doesn't count, so a unit can fire
    over its own wall.
- **Hooks.** Abilities can change cover in `los_checking` or `damage_calculating`
  (`ignores_cover`, `indirect`).
- **Melee and opportunity attacks** never get cover.

## Engagement and opportunity attacks

**Engagement only matters for opportunity attacks.** It does not restrict or modify
attacks: engaged units shoot and fight as normal, and shooting at an engaged unit is
unchanged.

- **Engaged.** A unit is **engaged** while it is adjacent to an enemy (reach 1; abilities
  may extend reach).
- **Trigger.** A move step that takes a unit from a square **within** enemy E's reach to
  a square **outside** it provokes an **opportunity attack** from E. This applies only if
  E has a reaction left and a melee weapon. E uses the first melee weapon in its loadout
  order (`opportunity_attack_triggering` hooks can cancel the attack or change the
  weapon).
  - Moving between squares that are both inside E's reach doesn't provoke.
- **Timing.** The attack is resolved **before the step**, through the full attack
  pipeline. Its `hits` are scaled by `rules.opportunity_attack_hit_percent` (default
  100). If the mover survives, it continues along its path.
- **Order.** When several enemies react to the same step, they attack in Speed order.
  Each reaction spends one of the enemy's reactions for the round.
- **Previews.** The movement planner shows the player which steps will provoke, before
  they commit to the move.

---

## Abilities: Python functions hooked into events

Abilities follow the Warcraft 3 World Editor trigger model: **event → conditions →
actions**. There is **no separate script language**. Conditions and actions are plain
**Python functions**, registered in a library under
`server/app/combat/ground/abilities/`. Content picks the functions for each trigger and
supplies their parameters. The core rules (attacks, movement, LoS, turns) raise events at
every decision point, so a hooked function can see and change any step.

### Writing a function

```python
# server/app/combat/ground/abilities/actions.py (and conditions.py)
from fractions import Fraction

from app.combat.ground.abilities.params import ArmorId, Params
from app.combat.ground.abilities.registry import action, condition
from app.combat.ground.hooks import DamageCalculating, HookContext


class MultiplyDamage(Params):
    percent: int


@action("multiply_damage", events={"damage_calculating"}, params=MultiplyDamage)
def multiply_damage(ctx: DamageCalculating, p: MultiplyDamage) -> None:
    ctx.multiply_damage(Fraction(p.percent, 100))


class ArmorIs(Params):
    armor: ArmorId


@condition("target_armor_is", params=ArmorIs)
def target_armor_is(ctx: HookContext, p: ArmorIs) -> bool:
    return ctx.target is not None and ctx.armor(ctx.target) == p.armor
```

- **`@condition(name, params, events=None)`** registers a function returning `bool`.
  **`@action(name, params, events=None)`** registers a function returning `None`.
  - `events` lists the events the function may be hooked into. `None` means any event.
- **`params`** is a Pydantic model (`Params`: frozen, no extra fields). The trigger's
  TOML parameters are checked against it **at startup**, including content ids such as
  `ArmorId`, `TagId`, `StatusId`, `Dice`.
- **`ctx`** is the **only interface to the combat.** The base class `HookContext` has:
  - read-only queries;
  - effects that change state;
  - the logged randomness `ctx.roll(dice)` and `ctx.chance(percent)`.

  Each event has its own context subclass (for example `DamageCalculating`). It adds that
  event's fields and **mutators**, so the type checker and the startup check both catch
  a function hooked into the wrong event.

### Content: wiring functions into abilities — `content/combat/abilities/*.toml`

```toml
[abilities.anti]
name_key = "ability.anti.name"
description_key = "ability.anti.desc"
kind = "weapon"                                   # weapon | passive | active | status
params = { armor = "armor", percent = "integer" } # filled in where the ability is used

[[abilities.anti.triggers]]
event = "damage_calculating"                      # scope defaults to "weapon"
conditions = [{ fn = "target_armor_is", armor = "$armor" }]
actions = [{ fn = "multiply_damage", percent = "$percent" }]
```

| Field | Meaning |
|---|---|
| `kind` | `weapon`: attached to a weapon; its triggers see only attacks made with that weapon. `passive`: attached to a unit. `active`: a usable action. `status`: a temporary ability applied by other abilities |
| `params` | The ability's own typed parameters. A reference such as `{ id = "anti", armor = "vehicle", percent = 150 }` supplies the values. Inside triggers they are referred to as `"$name"` |
| `triggers[]` | `event`, `scope`, `conditions[]` (all must hold), `actions[]` (run in order), `priority` (int, default 0) |
| `conditions[]` / `actions[]` | `{ fn = "<registered name>", …function params }`. The combinators `all_of`, `any_of` and `not` take nested `conditions` |
| active only | `ap_cost`, `cooldown` (rounds), `uses` (per combat), `targeting = { type, range, los, radius }`, where `type` is one of `self / ally / enemy / unit / square`. `on_cast = [actions…]` holds the actions |
| status only | `duration` (rounds), `stacking = refresh / stack / ignore`, `max_stacks`, `los_profile` override |

**Trigger scopes** say which events a trigger hears, relative to the ability's owner:

| scope | Fires when … |
|---|---|
| `weapon` | the event's attack uses the weapon that carries this ability (the default for `kind = weapon`) |
| `self` | the event's subject unit is the owner (the default for `passive`, `status`) |
| `self_target` | the owner is the event's target (defensive abilities) |
| `ally` / `enemy` | the subject is an ally (same side, not the owner itself) or an enemy of the owner (auras) |
| `any` | always |

**Composition first.** Most abilities are combinations of library functions with
parameters. Write a dedicated function only when an ability needs logic that combinations
can't express, such as loops over areas or multi-step effects. Such functions are still
small and reusable (for example `deal_hits_in_radius`).

### Load-time checks (fail fast at startup)
- Every `fn` exists in the registry.
- Function params validate against their Pydantic model, after `$param` substitution.
- Content ids exist (statuses, tags, terrain, overlays, unit types, weapon types).
- The function is allowed in the trigger's event, and `conditions` contain only
  conditions while `actions` contain only actions.
- Every ability reference on a unit or weapon supplies all of that ability's `params`
  with the right types.

### Execution model
- **Dispatch order.** When the engine raises an event, it collects the matching triggers
  from:
  - every living unit's abilities and statuses;
  - the weapons involved in the event.

  Triggers run in a deterministic order: `priority` (highest first), then the owner's
  position in the current round queue, then the ability's order on the unit, then the
  trigger index. A trigger runs its actions only if all its conditions are true.
- **Transactional runs.** Each trigger run works on a **working copy** of the state
  through `ctx`. State is made of frozen dataclasses, so a copy is cheap. A run either
  commits as a whole or is discarded.
- **Errors.** If a hooked function raises, its trigger run is **rolled back** and a
  `hook_error` event is logged. The fight continues. Tests run with `strict=True`, which
  re-raises the error.
- **Cascades.** A `ctx` effect raises its own events. For example, `ctx.deal_hits`
  raises `unit_damaged` and `model_killed`, and those dispatch further triggers (nested
  runs). The nesting depth is capped at `rules.max_trigger_depth` (default 8). Past the
  cap, events are still logged but **no further triggers fire**.

### Determinism and purity rules for ability functions
Ability modules are part of the pure core (rules 2–3). They must follow these rules:
- **Never import `random`, `time`, `datetime`, I/O, network, DB or `app.persistence`.**
  All randomness goes through `ctx.roll` and `ctx.chance`, which use the combat RNG and
  log each draw together with the ability id.
- **No floats.** Use `int` and `Fraction`.
- **No module-level mutable state.** Change the combat only through `ctx` methods.
- **Iterate in a defined order.** Iteration order must be deterministic. `ctx` queries
  return lists in a defined order (unit index or square order), never sets.

A test parses every module under `abilities/` (AST import scan) and fails on any
forbidden import. The rest is enforced in review.

**Versioning.** Ability functions are engine code. A change that alters the outcome of a
fight bumps `COMBAT_RULES_VERSION`. Exact replays are guaranteed only for the same rules
version and content hash.

Rules version log:
- **v1:** initial engine.
- **v2:** each hit picks its victim (`hit_allocating`) before damage is computed, so
  redirected hits use the victim's armor and cover.

### Event catalogue
Each event has a **subject** (the unit `scope` matches against), context fields, and
the mutators its context class adds.

| Event | Subject / target | Context fields | Mutators |
|---|---|---|---|
| `combat_started` | – | – | – |
| `round_started`, `round_ended` | – | `round` | – |
| `activation_started`, `activation_ended` | unit | – | – |
| `unit_waited` | unit | – | – |
| `stat_calculating` | unit | `stat` (`speed`, `movement`, `action_points`, `reactions`), `value` | `add_stat(int)`, `multiply_stat(Fraction)` |
| `step_moving` | mover | `from_square`, `to_square` | `cancel_step()`, `set_step_cost(int)` |
| `step_moved` | mover | `from_square`, `to_square` | – |
| `opportunity_attack_triggering` | reactor / mover | `weapon` | `cancel_opportunity_attack()`, `set_opportunity_weapon(weapon)` |
| `attack_validating` | attacker / target | `weapon`, `distance` | `allow_without_los()`, `add_range(int)`, `forbid_attack(reason_key)` |
| `attack_declared` | attacker / target | `weapon` | `set_ap_cost(int)` |
| `hits_calculating` | attacker / target | `weapon`, `hits` | `add_hits(int)`, `multiply_hits(Fraction)` |
| `damage_calculating` | attacker / target | `weapon`, `roll`, `cover` | `add_damage(int)`, `multiply_damage(Fraction)`, `set_cover(bool)`, `set_armor_percent(int)` |
| `hit_allocating` | attacker / target | – (runs before damage is computed) | `redirect_hit(unit)`, `prevent_hit()` |
| `attack_resolved` | attacker / target | `weapon`, `total_damage`, `kills` | `keep_movement()` |
| `unit_damaged` | damaged unit / source | `damage`, `kills`, `weapon` (may be `None`) | – |
| `model_killed` | victim / source | `role` | – |
| `unit_destroyed` | victim / source | – | – |
| `los_checking` | observer / target | `los`, `cover` | `set_los(bool)`, `set_cover(bool)` |
| `ability_casting` | caster / target | `ability` | `forbid_cast(reason_key)` |
| `ability_cast` | caster / target | `ability`, `cast_unit`, `cast_square` | – |
| `status_applied`, `status_expired` | holder | `status` | – |

Every context also has `ctx.owner` (the ability's holder), `ctx.unit` (the subject) and
`ctx.target`, which is `None` when there is no target.

### `HookContext` API (v1)
Grouped as below. The API grows as abilities need it, and every addition gets a test.

- **Queries:**
  - `is_alive(u)`, `unit_type(u)`, `has_tag(u, tag)`, `armor(u)`;
  - `is_enemy(a, b)`, `is_ally(a, b)`;
  - `models(u)`, `max_models(u)`, `hp(u)`, `hp_missing(u)`, `stat(u, id)`;
  - `has_status(u, id)`, `status_stacks(u, id)`;
  - `is_engaged(u)`, `has_moved(u)`, `has_attacked(u)`;
  - `distance(a, b)`, `square_of(u)`, `has_los(a, b)`, `in_cover(target, attacker)`;
  - `ap_left(u)`, `movement_left(u)`;
  - `units_in_range(square, r)`, `enemies_in_range(u, r)`, `allies_in_range(u, r)`,
    `units_in_los(u)`;
  - `squares_in_radius(square, r)`, `terrain(square)`, `is_passable(square)`,
    `unit_at(square)`;
  - `round`.
- **Random (logged):** `roll(dice) -> int`, `chance(percent) -> bool`.
- **Effects** (each raises its own events):
  - `deal_hits(source, target, hits, dice, weapon_type, ranged)` uses the **full damage
    pipeline**: armor table, cover, hooks and allocation.
  - `deal_true_damage(target, amount)` is a single hit that bypasses armor, cover and
    multipliers.
  - `free_attack(source, target, weapon)` attacks without spending AP and without the
    once-per-activation limit.
  - `heal(u, amount)` heals the wounded model only; it never revives.
  - `revive_models(u, n)`.
  - `apply_status(u, id, duration)`, `remove_status(u, id)`.
  - `grant_ap(u, n)`, `grant_movement(u, n)`, `set_reactions(u, n)`, `end_activation(u)`.
  - `push(u, from_square, n)`, `teleport(u, square)`.
  - `spawn_unit(unit_type, side_of, square, models)` returns a `UnitId`.
  - `place_overlay(square, id, rounds)`, `remove_overlay(square, id)`.
  - `log_message(key, **params)` posts an i18n line to the combat log.

### Standard library: the core weapon keywords
These live in `content/combat/abilities/core.toml`, and their functions in
`abilities/actions` and `abilities/conditions`. They double as reference examples.

```toml
[abilities.assault]           # may keep moving after firing
kind = "weapon"
[[abilities.assault.triggers]]
event = "attack_resolved"
actions = [{ fn = "keep_movement" }]

[abilities.heavy]             # can't fire after moving this activation
kind = "weapon"
[[abilities.heavy.triggers]]
event = "attack_validating"
conditions = [{ fn = "owner_has_moved" }]
actions = [{ fn = "forbid_attack", reason_key = "attack.forbidden.heavy_moved" }]

[abilities.blast]             # +1 hit per N models in the target
kind = "weapon"
params = { per_models = "integer" }
[[abilities.blast.triggers]]
event = "hits_calculating"
actions = [{ fn = "add_hits_per_target_models", per_models = "$per_models" }]

[abilities.ignores_cover]
kind = "weapon"
[[abilities.ignores_cover.triggers]]
event = "damage_calculating"
actions = [{ fn = "set_cover", value = false }]

[abilities.indirect]          # no LoS needed; without LoS, the target counts as in cover
kind = "weapon"
[[abilities.indirect.triggers]]
event = "attack_validating"
actions = [{ fn = "allow_without_los" }]
[[abilities.indirect.triggers]]
event = "damage_calculating"
conditions = [{ fn = "not", conditions = [{ fn = "owner_sees_target" }] }]
actions = [{ fn = "set_cover", value = true }]

[abilities.reach]             # melee weapon with longer reach
kind = "weapon"
params = { squares = "integer" }
[[abilities.reach.triggers]]
event = "attack_validating"
actions = [{ fn = "add_range", squares = "$squares" }]
```

### Unit ability examples

```toml
[abilities.regenerate]                 # heal at the start of each activation
kind = "passive"
params = { amount = "integer" }
[[abilities.regenerate.triggers]]
event = "activation_started"
conditions = [{ fn = "owner_is_damaged" }]
actions = [{ fn = "heal_owner", amount = "$amount" }]

[abilities.bodyguard]                  # take hits aimed at an adjacent allied character
kind = "passive"
[[abilities.bodyguard.triggers]]
event = "hit_allocating"           # subject = the attacker, target = the unit being hit
scope = "any"
conditions = [
  { fn = "target_is_ally" },
  { fn = "target_has_tag", tag = "character" },
  { fn = "target_within", squares = 1 },
]
actions = [{ fn = "redirect_hit_to_owner" }]

[abilities.rally_cry]                  # aura: allied infantry within 3 get +1 movement
kind = "passive"
[[abilities.rally_cry.triggers]]
event = "stat_calculating"
scope = "ally"
conditions = [
  { fn = "stat_is", stat = "movement" },
  { fn = "unit_has_tag", tag = "infantry" },
  { fn = "unit_within", squares = 3 },
]
actions = [{ fn = "add_stat", amount = 1 }]

[abilities.disengage]                  # status: leaving reach provokes nothing
kind = "status"
duration = 1
[[abilities.disengage.triggers]]
event = "opportunity_attack_triggering"
scope = "self_target"
actions = [{ fn = "cancel_opportunity_attack" }]

[abilities.smoke_charge]               # active: a smoke cloud that blocks LoS
kind = "active"
ap_cost = 1
cooldown = 3
targeting = { type = "square", range = 8, los = true, radius = 1 }
on_cast = [{ fn = "place_overlay_in_radius", overlay = "smoke", radius = 1, rounds = 2 }]

[abilities.frag_charge]                # active: D3 explosive hits to every model in the blast
kind = "active"
ap_cost = 1
uses = 1
targeting = { type = "square", range = 6, los = true, radius = 1 }
on_cast = [{ fn = "deal_hits_in_radius", radius = 1, hits_per_model = 1, dice = "D3", weapon_type = "explosive" }]
```

A dedicated function, written for logic that composition can't express:

```python
class HitsInRadius(Params):
    radius: int
    hits_per_model: int
    dice: Dice
    weapon_type: WeaponTypeId


@action("deal_hits_in_radius", events={"ability_cast"}, params=HitsInRadius)
def deal_hits_in_radius(ctx: AbilityCast, p: HitsInRadius) -> None:
    for unit in ctx.units_in_range(ctx.cast_square, p.radius):  # ordered by unit index
        ctx.deal_hits(
            ctx.owner, unit, ctx.models(unit) * p.hits_per_model,
            p.dice, p.weapon_type, ranged=True,
        )
```

---

## Engine architecture — `server/app/combat/ground/` (pure)

```
engine.py         public API: start_combat, legal_actions, apply_action, replay,
                  CombatRecord, COMBAT_RULES_VERSION, IllegalAction, SetupError
setup.py          CombatSetup / UnitSetup, build_unit (fill group), board validation
state.py          frozen dataclasses: UnitState, GroupState, StatusState, OverlayState,
                  Activation, Outcome, CombatState (round/wait queues, active unit)
board.py          Square, Board (from_rows for ASCII maps), footprints, Chebyshev distance
actions.py        Move(path) | Attack(weapon, target) | UseAbility(id, target) | Wait | Skip
events.py         public event-log dataclasses + log_hash (what the client animates,
                  what replays and golden tests compare)
resolver.py       the working object of one call: state, logged RNG (roll/chance/
                  stochastic rounding), hook dispatch (collection, ordering,
                  transactional runs, depth cap), effects used by ctx
hooks.py          HookContext + one context subclass per event (fields, mutators)
view.py           BoardView: terrain + overlays, occupancy, LoS profiles, fits/step cost
turn_order.py     rounds, ticking durations, queue building, ties, Wait, end of combat
movement.py       Dijkstra over move costs, footprints, corner rule, OA detection/preview
los.py            exact doubled-integer segment-vs-square interiors, blockers, screens,
                  directional + area cover, best line for big units
attack.py         the attack pipeline (validate → hits → per-hit damage → allocate)
ability_use.py    active abilities: targeting checks, paying, on_cast
dice.py           Dice parsing (rolling lives in the resolver, so it is logged)
ruleset.py        compile content → CombatRuleset: binds triggers to registered functions,
                  validates params/events/ids; load_ruleset() at startup
abilities/
  registry.py     @condition / @action decorators, the name → function registry
  params.py       Params base + content-id types (ArmorId, TagId, StatusId, DiceParam, …)
  conditions.py   reusable conditions (all_of / any_of / not are built into the compiler)
  actions.py      reusable actions (damage, hits, validation, stats, statuses, areas, …)
server/app/content/combat.py       Pydantic schemas + loader for content/combat/**.toml
```
A v1 greedy AI (`ai.py`, `choose_action(state, rng)`) is not written yet.

- **RNG.** One `random.Random` per combat, seeded from the world sim (via
  `derive_seed`, as in `server/app/world/seeds.py`). The engine never touches global
  `random`.
- **Running combats:** the engine runs inside **combat worker processes**, wrapped by
  `CombatInstance`. The doc for this is
  [architecture › Combat instances](architecture.md#combat-instances), which covers:
  - placement on workers;
  - seat checks;
  - the hotseat demo from `content/combat/demo.toml`;
  - timers;
  - persistence of the record (setup, seed, content hash, rules version, actions) with
    write-behind;
  - recovery by `replay` after a restart.
- **Protocol:** clients send `combat.action {combat_id, action}` over `/ws`. The server
  pushes `combat.events` (the public event log, including rolls), `combat.legal` (moves
  and targets for the active unit) and `combat.snapshot`. The client only animates and
  highlights. See [protocol](protocol.md#websocket).
- **Performance budget:** `apply_action` plus the legal-action recompute must stay
  **≤ 5 ms p95** on a 32×32 board (see
  [architecture › Scalability](architecture.md#scalability-and-capacity-model)).
  - Today it is about 18–24 ms, mostly from scanning every square for area abilities and
    recomputing legal actions after each action.
  - Planned fixes: cache `LegalActions` per state, cheaper square-target enumeration, a
    single legal recompute per action, and a benchmark test.

### Content files — `content/combat/`

| File | Contents |
|---|---|
| `rules.toml` | `default_board` (32×32), `board_min`, `board_max`, `round_limit`, `draw_margin_percent`, `activation_timer_s`, `max_models_per_unit`, `opportunity_attack_hit_percent`, `friendly_units_screen`, `first_round_no_attacks`, `max_trigger_depth` |
| `terrain.toml` | terrain types + overlays |
| `tags.toml` | the allowed unit tags |
| `weapon_types.toml` | weapon types (name keys) |
| `damage_table.toml` | the full weapon-type × armor percentage matrix |
| `weapons.toml` | weapons |
| `units.toml` | units with their loadout groups |
| `abilities/*.toml` | abilities and statuses, wired to registered functions (`core.toml` = the keywords) |

All player-facing names use i18n keys in `locales/en.json` and `locales/ua.json`.

The starter roster is original sample data for two factions:
- **Concord:** `line_troopers`, `heavy_team`, `warden` (a character), and the 2×2 vehicle
  `bastion_walker`.
- **Brood:** `ravager_swarm` (10–30 models), `spitter_brood`, and the 2×2 monster
  `brood_tyrant`.

### Implementation notes (v1)
Details settled while building the engine. They are binding until changed here:
- **Sides.** Combats support **N sides** (≥ 2). Sides are ints; ally means the same side.
  - The tie-break order is a seeded shuffle of the sides, rotated by one each round.
  - Annihilation leaves the last side standing.
  - At the round limit, a side scores `points × surviving models ÷ starting models` per
    unit. Every side within `draw_margin_percent` of the leader shares a draw.
- **Targets.** Attacks may only target enemies, and only living ones.
- **Stochastic rounding.** It is used for damage and for fractional hit counts. Stat
  modifiers (`stat_calculating`) are floored, with no RNG.
- **Engagement reach.** It is fixed at 1 in v1. The `reach` keyword extends a melee
  weapon's attack range, not the zone that triggers opportunity attacks.
- **Opportunity attacks.**
  - The reactor uses the first melee weapon in its loadout order.
  - Its reaction is spent only if the attack is actually made (it passes
    `attack_validating`).
- **Moves that stop early.** A step can be cancelled, run out of movement after a hook, or
  be blocked by a state change. If the unit then stands on a friend's square, it falls
  back to the last free square it passed (`unit_repositioned`, reason `blocked_end`).
- **Wait.** Wait doesn't fire `activation_ended`. The unit's activation resumes later.
- **Timers.** The engine has no clock. The server shell enforces `activation_timer_s` by
  sending `Skip`.
- **Legal-action previews.** These run the validation hooks on throwaway copies of the
  state with a dummy RNG. A hook can never change the real combat through a preview.
- **Illegal actions.** `IllegalAction` (an i18n `reason` key) leaves the state and the
  RNG exactly as they were, so the recorded action list stays replayable.
- **Active abilities.** `on_cast` runs as a transactional trigger owned by the caster.
  Then `ability_cast` is dispatched to every other listener.
- **Statuses.**
  - They tick at round start, so `rounds = 1` lasts until the next round begins.
  - Cooldowns tick at round start too.
  - With several statuses, the most recently applied `los_profile` override wins.

---

## Test invariants (each is a test)
- **Determinism:** the same setup, seed and actions always give the same event log.
  Golden fights are stored as event-log hashes.
- **LoS geometry** is symmetric, and touching a corner never blocks.
  - Blockers, screens and footprints behave as specified.
- **Movement:**
  - paths never exceed the pool or enter impassable or enemy squares;
  - corner cutting is rejected;
  - 2×2 units fit their path;
  - boards of any size within the limits work.
- **Damage:**
  - no spill: one hit never kills two models;
  - the wounded model takes the next hit;
  - casualty priority is respected;
  - HP never goes below 0.
- **Cover:** cover halves the *expected* damage, checked over a fixed set of seeds.
  Flanking removes directional cover, and a wall next to the attacker doesn't count.
- **Engagement:**
  - every weapon is usable while engaged, and attack resolution is unchanged;
  - opportunity attacks trigger only when leaving reach, and each one spends a reaction;
  - the hit percent is applied;
  - if the mover dies mid-path, the move stops there.
- **Turn order:** Speed ordering, the tie rotation, the wait queue in reverse order, and
  dead units removed from the queues.
- **Hooks:**
  - startup rejects unknown `fn`s, wrong params, wrong events, missing ability params and
    unknown ids;
  - a run that raises is rolled back completely;
  - the cascade depth cap holds;
  - dispatch order is deterministic;
  - the import scan finds no forbidden imports in `abilities/`.
- **Every ability in content has a scenario test.** A small board where the ability must
  visibly change the outcome. Content CI fails if any ability lacks one.

---

## Issues raised

Design risks that could frustrate players, with the mitigation built into the rules
above.

1. **Unlimited models per unit.**
   - *Risk:* balance breaks (a huge horde's opportunity attack, `blast`), the badge
     becomes unreadable, and resolution costs more.
   - *Mitigation:* `models.max` per unit type, plus the engine cap
     `rules.max_models_per_unit` (default 100).
2. **Speed dominance and alpha strikes.**
   - *Risk:* the faster side shoots first every round.
   - *Mitigation:* Wait lets slower players react. Deployment zones on a 32×32 board
     should start out of range of most weapons, and the optional `first_round_no_attacks`
     rule is available.
3. **Async waiting.**
   - *Risk:* with per-unit turns, a player may watch several enemy activations in a row.
   - *Mitigation:* the activation timer with auto-Skip. Ship PvE first.
4. **Cover rounding.**
   - *Risk:* halving small integers makes 1-damage weapons deal either always 0 or
     always 1.
   - *Mitigation:* stochastic rounding keeps expected values exact.
5. **Melee value when shooting is unrestricted in engagement.**
   - *Risk:* engaged ranged units shoot back at full strength, so melee units only gain
     from their own damage and from opportunity attacks.
   - *Mitigation:* balance through content: melee weapons with high `hits`, damage-table
     percentages, and abilities (for example a `brawler` ability that adds damage
     against engaged targets). Watch this in balance testing.
6. **Friendly units screening your own shots.**
   - *Risk:* it's realistic, but can feel bad: your own squad gives the enemy cover.
   - *Mitigation:* `rules.friendly_units_screen` can turn it off. The UI must show the
     cover icon before the player confirms an attack.
7. **Big units as mobile walls.**
   - *Risk:* `block` profiles let vehicles hide infantry completely.
   - *Mitigation:* that's intended (a tactical choice). Watch it during balancing, and use
     the `screen` profile for lighter vehicles.
8. **"Character" as an armor type.**
   - *Risk:* characters usually need protection from snipers, and an armor type only
     feeds the damage table.
   - *Mitigation:* `character` is both an armor type and a tag; `bodyguard`-style
     abilities protect them. Leaders attaching to units is an open question.
9. **A 32×32 board on a phone.**
   - *Risk:* the whole board can't be shown at a usable tap size.
   - *Mitigation:* the camera auto-centres on the active unit, and pinch-zoom has a
     tactical zoom level and an overview level. Reachable squares, targets, cover and
     opportunity-attack warnings are highlighted when the unit is selected, and a tap
     always previews before it commits. A minimap is optional later.
10. **Ability functions are full Python.**
    - *Risk:* functions can break determinism (hidden RNG, set ordering, floats), crash a
      fight, or be slow.
    - *Mitigation:*
      - all access goes through `ctx`;
      - the import scan;
      - rollback when a function raises;
      - the depth cap;
      - `COMBAT_RULES_VERSION` bumps;
      - mandatory scenario tests per ability;
      - an AI-vs-AI batch simulator for balance (future).

      Content authors combine existing functions in TOML; new functions go through
      review.
11. **Automatic casualty choice.**
    - *Risk:* owners can't pick which models die.
    - *Mitigation:* content `casualty_priority` for now. A per-army preference may come
      later.
12. **Long fights on mobile.**
    - *Mitigation:* `round_limit` with a points decision. Objectives and morale come
      later.

## Open questions
- Morale and suppression. These could be modelled as statuses plus a "leave the
  battlefield" effect.
- Squad persistence: veterancy, carrying casualties over between fights, and
  reinforcement cost (economy).
- Objectives and victory conditions beyond annihilation or points.
- Deployment rules and zones on variable board sizes; reserves and deep strike
  (`teleport` plus a deployment hook).
- Leaders attaching to units.
- Overwatch and other reactions beyond opportunity attacks (a `reaction_window` event).
- PvP rules: per-activation timer values, AFK and forfeit, matchmaking.
- Generating battle maps from planet-surface regions, and choosing the board size per
  region ([world-gen](world-gen.md)).
- How the world sim starts a combat, and how the result flows back.
- Archiving content snapshots and rules versions, for replays of old fights.
