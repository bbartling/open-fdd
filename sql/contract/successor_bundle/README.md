# Successor synthetic contract bundle (Soft-OPEN scaffold)

**Soft-OPEN ≠ FQ.** Preserve the original warehouse handoff hash; do not edit
goldens in place.

## Original archive (immutable)

| Field | Value |
| --- | --- |
| File | `OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip` |
| SHA256 | `0597b6d6492750edae2c994ac5d2fcbb26a8a2bd6c122013da5399b94b8b24ec` |

## Successor (this scaffold)

Proposed contents (generated from tagged source/CI — not hand-edited goldens):

- `manifest.json` — contract version, source commit, schema range, file hashes
- `schema/` — ordered migrations + helpers
- `fdd/` — all 77 SQL templates + registry
- `analytics/` — SQL pack + registry + known-answer stubs
- `fixtures/` — synthetic RDF/history Soft-OPEN later
- `checksums` — pack ledger aligned with `sql/contract/manifest.json`

BPS and OSS pin the same successor pack hash when released. Twin layers must not
fork equations.

See `.cursor/plans/post_wave_x_363_softopen_residuals_20261014.plan.md` § R8c.
