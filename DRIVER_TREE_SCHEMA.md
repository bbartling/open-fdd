# Driver tree JSON schema (v1.0.0)

Runtime snapshots under `workspace/data/drivers/bacnet/driver_tree.json` are **generated artifacts**, not authoritative site configuration.

## Envelope fields (API responses)

| Field | Description |
|-------|-------------|
| `schema_version` | Semver of this schema (`1.0.0`) |
| `generated_at` | RFC3339 timestamp when the API built the response |
| `source` | `real` \| `simulated` \| `fixture` \| `imported` |
| `generated_from_demo_fixture` | `true` when CI/demo fixtures are in use |
| `stale_after_seconds` | Hint for UI staleness warnings (default 3600) |
| `validation.ok` | Whether snapshot passed validation |
| `validation.warnings` | Non-fatal issues (legacy files, missing labels) |
| `validation.errors` | Fatal issues (demo data in live mode) |
| `provenance` | Workspace path, modes, snapshot file path |

## Driver node fields

| Field | Description |
|-------|-------------|
| `id` | Stable driver key (`bacnet-ip`, `modbus-tcp`, …) |
| `label` | Operator display name |
| `enabled` | Operator enable flag |
| `status` | `online` \| `offline` \| `degraded` |
| `mode` | `live` \| `simulated` \| `test` |
| `source` | Data origin for this driver row |
| `last_success_at` | Last successful poll/discovery |
| `last_error_at` / `last_error` | Last failure (live mode honesty) |

## Point fields

Points should include `id`, protocol identifiers (`object_id`, `register`, …), `writable`, `haystack_id`, `fdd_input`, and `source` where applicable.

## Live BACnet rules

When `OPENFDD_BACNET_MODE=live`:

- Must not contain `AHU-1 Controller`, `192.168.1.100`, or demo override `58.0`
- Empty tree is valid; degraded status is honest
- Discovery/sync APIs populate the workspace snapshot

Validate in Rust: `edge/src/drivers/framework.rs` tests.
