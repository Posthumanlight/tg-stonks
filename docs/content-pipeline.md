# Content Pipeline

How authored game data (items, recipes, hulls, modules, unit types, factions) is
defined, validated, localized and delivered to the client.

## Decided
- Content lives in `content/*.toml`, one file (or folder) per content type.
- Loaded and validated by Pydantic models at server startup; invalid content fails fast.
- Balance numbers live in content, not in code.
- Player-facing names/descriptions are i18n keys (e.g. `item.iron_ore.name`), resolved
  via `locales/en.json` and `locales/ru.json`. Every key must exist in both.
- IDs are stable string slugs (e.g. `iron_ore`); never reuse or rename a shipped ID.

## Open questions
- How the client gets content: bundled at build time vs served by `/api/static`.
- Content versioning / hash so clients detect stale data.
- Tooling: a validation CLI and a check that every i18n key is present in all locales.
- Sprite/atlas naming convention linked to content IDs.
