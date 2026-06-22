# Driver storage design

## Current (3.2.0)

| Layer | Role |
|-------|------|
| Rust typed model | `edge/src/drivers/framework.rs` — validation, provenance, live/simulated guards |
| Workspace JSON | Runtime snapshot + export format for UI |
| CSV under `workspace/overrides/` | Override scan audit trail |

JSON snapshots are **regenerable**. Safe to delete `workspace/data/drivers/bacnet/driver_tree.json` and re-run sync-discovery in live mode.

## Not committed

- Live machine-specific `workspace/` trees (bind IPs, discovered points)
- Operator override CSV history (local audit)

## Fixtures

Place sanitized snapshots under `edge/tests/fixtures/` for unit tests only.

## Future SQLite (optional)

Recommended durable tables when scaling beyond bench:

1. `discovered_devices` — instance, address, router, last_seen
2. `point_catalog` — point id, object_id/register, haystack_id, writable
3. `scan_runs` — scan_id, source, protocol_proof JSON, started_at
4. `override_events` — normalized override rows (CSV remains export)
5. `driver_health` — status transitions

Rust interfaces (`TreeEnvelope`, `ValidationResult`, `/api/drivers/tree`) are designed so SQLite can back `build_driver_tree_envelope()` without React changes.

## Permissions

Workspace must be writable by the container user. Check `GET /api/health/workspace`.
