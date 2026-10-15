# Successor synthetic contract bundle (Soft-OPEN 3.6.7)

**Soft-OPEN ≠ FQ.** Preserve the original warehouse handoff hash; do not edit
goldens in place.

## Original archive (immutable)

| Field | Value |
| --- | --- |
| File | `OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip` |
| SHA256 | `0597b6d6492750edae2c994ac5d2fcbb26a8a2bd6c122013da5399b94b8b24ec` |

## Soft-OPEN contents (this bundle)

| Path | Role |
| --- | --- |
| `manifest.softopen.json` | Bundle status + original hash pin |
| `FILES.sha256` | Ledger aligned with `sql/contract/manifest.json` |
| `../manifest.json` | Canonical contract (version + pack_sha256) |
| `../../analytics/` | Soft-OPEN analytics SQL pack |
| `../../fdd/postgres/rules/` | 77 SQL templates |
| `../../schema/` | Ordered Timescale migrations |
| `../../../scripts/softopen_r6_harness_check.sh` | Smoke pin harness |

BPS and OSS pin the same successor pack hash when released. Twin layers must not
fork equations.

See `.cursor/plans/post_wave_x_363_softopen_residuals_20261014.plan.md` § R8c.
