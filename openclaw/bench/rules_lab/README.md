# Rules lab (no duplicate YAML)

Canonical FDD rule YAML for the running stack lives under **`stack/`** (mounted into containers), not under `openclaw/`. This directory intentionally **does not** copy rule files from the old automated-testing repo to avoid silent drift.

- **Edit and sync rules** via the platform workflow documented in [`docs/rules/overview.md`](../../../docs/rules/overview.md) and [`docs/configuration.md`](../../../docs/configuration.md).
- **Optional testbed copies:** If you need bit-identical fixtures for a lab host, keep them **outside** this repo or in a private branch; do not treat `openclaw/` as a second source of truth for production rules.
