# Parity evidence log (P1-M0-02 seed / M1 updates)

| date | capability_id | fixture hash | source commit | engine versions | result | mismatch class | PR |
|------|---------------|--------------|---------------|-----------------|--------|----------------|-----|
| 2026-07-31 | catalog | see `tests/react_parity/manifest.json` | pending merge | exporter v1 | fixtures seeded | — | P1-M1 |

## Rules

- Record immutable commit SHAs and fixture content hashes.
- Classify mismatches: EXACT / NUMERIC / TEMPORAL / INTERACTION / VISUAL / ARTIFACT / SECURITY / UNKNOWN.
- UNKNOWN blocks “parity done.”
- Do not treat FITTED ECM sheet≈E+ as independent validation (see ECM honesty docs).

Screenshots: deferred until display/CI capture job exists; scenarios listed in
[`evidence/INTERACTION_BASELINE.md`](evidence/INTERACTION_BASELINE.md).
