---
name: open-fdd-drivers
description: LLM-assisted driver bundles for Open-FDD — validate draft configs via the bridge without applying until the operator approves.
---

# Open-FDD drivers (OpenClaw)

## When to use

- Configuring **CSV, weather, onboard, or headless BACnet** drivers.
- Operator pastes **vendor column names** or sample CSV headers and wants a **column_map** or driver JSON aligned with Open-FDD rules.

## Preconditions

- Bridge: `http://127.0.0.1:8765` (or LAN / `host.docker.internal` from containers).
- OpenAPI: `GET /docs` — locate **`/config/drivers/validate`** (or export) for this build.

## Workflow

1. **Discover** — `GET {bridge}/config/drivers/export` if present; else ask the operator for current driver YAML/JSON.
2. **Draft** — Produce driver config and **column_map** entries that match **`open_fdd`** rule inputs (see repo `docs/column_map_resolvers.md` and bundled default rules).
3. **Validate only** — `POST {bridge}/config/drivers/validate` with the **draft bundle**; do not treat success as applied until the operator confirms a write endpoint.
4. **Apply** — Only use mutating routes the operator explicitly authorizes (e.g. site-scoped driver save if exposed).

## Safety

- Prefer **validate** endpoints over blind writes.
- Redact **tokens** and **building IDs** in logs and chat transcripts.

## References

- `README.md` (drivers), `docs/howto/desktop_app.md`, `scripts/OPENCLAW_RUNBOOK.md`.
