# Content Pipeline

How authored game data (items, recipes, hulls, modules, unit types, factions) is
defined, validated, localized and delivered to the client.

## Decided
- Content lives in `content/*.toml`, one file (or folder) per content type.
- Loaded and validated by Pydantic models at server startup; invalid content fails fast.
- Balance numbers live in content, not in code.
- Player-facing names/descriptions are i18n keys (e.g. `item.iron_ore.name`), resolved
  via `locales/en.json` and `locales/ua.json`. Every key must exist in both.
- IDs are stable string slugs (e.g. `iron_ore`); never reuse or rename a shipped ID.
- **Ground-combat abilities** (`content/combat/abilities/*.toml`) are triggers that wire
  registered Python condition and action functions into engine events, with typed
  parameters.
  - At startup, function names, parameters and events are validated, and invalid wiring
    fails fast.
  - Every ability needs a scenario test.
  - See [combat-ground](combat-ground.md#abilities-python-functions-hooked-into-events).
- **Locale files** are flat JSON objects (`{"planet_type.lava.name": "Lava world"}`) that
  the client bundles at build time.
  - Under "generate content only for English", new keys get English placeholder values in
    `ua.json` until someone translates them.
  - Tests:
    - `client/src/i18n/i18n.test.ts`: both locales have the same keys, with no empty
      values;
    - `server/tests/world/test_locale_keys.py`: every `name_key` in the world-gen content
      exists in every locale.

## Open questions
- How the client gets content: bundled at build time vs served by `/api/static`.
- Content versioning / hash so clients detect stale data.
- Tooling: a standalone validation CLI.
- Sprite/atlas naming convention linked to content IDs.
