"""Ground-combat rules engine (pure, seeded). Spec: docs/combat-ground.md.

Public API lives in `app.combat.ground.engine`. This package init stays import-free so
that `app.content.combat` can import `dice` without cycles.
"""
