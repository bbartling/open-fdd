# Soft-OPEN R8a — tip-safe schema/contract probe

Soft-OPEN ≠ FQ.

## What Soft-OPEN proves

| Probe | Soft-OPEN |
| --- | --- |
| `GET /api/admin/schema-contract` | Hub-admin **read-only** |
| Live `seed_meta.schema_version` | Reported when present; missing is honest |
| Pinned `sql/contract/manifest.json` | `contract_version` + `pack_sha256` |
| Migrator apply | **Not run** — Soft-OPEN ≠ bootstrap/FQ migrator |

## Explicit non-claims

- Soft-OPEN does **not** destroy or recreate volumes.
- Soft-OPEN does **not** treat `CREATE TABLE IF NOT EXISTS` as the migrator.
- Soft-OPEN tip probe ≠ FQ schema migration proof.

Locks: no Soft-OPEN backups · volume Deletes owner-UI BLOCKED · Soft-OPEN ≠ FQ.
