# Hostile ZIP fixture catalog (CAP-UPLOAD)

Placeholders for CI hostile archive suite. Archives are **generated at test time** in Rust (`edge/src/csv_ingest/package.rs` unit tests) — no committed binary zips.

## cases.json

| id | relative path | expected rejection |
|---|---|---|
| `zip_slip` | `../../etc/passwd` | `path traversal rejected` |
| `symlink` | `link_to_outside` via `ZipWriter::add_symlink` (S_IFLNK) | `symlink entries are not allowed` |
| `extension_spoof` | `evil.csv.exe` | fails closed on missing `manifest.json` / maps (not a valid package) |

## Rust defenses (`read_zip_entries`)

Rejected before ingest:

- Path traversal (`../`) and absolute paths (`/…`, `C:\…`)
- Symlink entries (zip symlink marker or Unix mode `0o120000`)
- Entry count over `OPENFDD_MAX_ENTRIES` (default 2000)
- Uncompressed total over `OPENFDD_MAX_UNCOMPRESSED_MB` (default 512)
- Per-entry compression ratio > 100:1 (zip bomb heuristic)
- Duplicate paths differing only by case
- Declared size larger than bytes actually read

Nested `*.zip` members inside a valid package are **not extracted**; ingest warns and continues. Zip-only uploads without `manifest.json` fail closed.

## React parity

- Upload UI: `frontend/web/src/pages/UploadPage.tsx` → `POST /api/csv/import/package` (multipart)
- Client: `frontend/web/src/api/uploadApi.ts`
