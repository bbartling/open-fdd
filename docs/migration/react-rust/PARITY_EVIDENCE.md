# Parity evidence log (P1-M0-02 seed / M1 updates)

| date | capability_id | fixture hash | source commit | engine versions | result | mismatch class | PR |
|------|---------------|--------------|---------------|-----------------|--------|----------------|-----|
| 2026-07-31 | CAP-ERRORS / shell | LAYOUT_GEOMETRY.md + AppShell tests | branch `feat/p1-m3-01-layout-tokens` | Vite React shell | Frame tokens + section order + collapse; screenshots still deferred to visual harness | INTERACTION | P1-M3-01 |
| 2026-07-31 | catalog (all CAP-*) | `tests/react_parity/manifest.json` | branch `feat/p1-m1-fixtures-oracle-baseline` | exporter schema `openfdd.react_parity.reference` | M1 fixtures + oracle byte-stable; interaction baseline NONVISUAL → M3 | — | P1-M1 / #615 |

## M1 gate checklist

- [x] Deterministic fixture catalog under `tests/react_parity/` with content hashes
- [x] Oracle-only `tools/react_parity/export_reference_json.py` + 3-run byte stability test
- [x] Interaction baseline index covers **all** capability rows (`evidence/INTERACTION_BASELINE.md`)
- [x] Visual screenshots classified **NONVISUAL (M3 visual)** — not claimed as done
- [x] Regeneratable with: `pytest tests/react_parity -q`

## Rules

- Record immutable commit SHAs and fixture content hashes.
- Classify mismatches: EXACT / NUMERIC / TEMPORAL / INTERACTION / VISUAL / ARTIFACT / SECURITY / UNKNOWN.
- UNKNOWN blocks “parity done.”
- Do not treat FITTED ECM sheet≈E+ as independent validation (see ECM honesty docs).
- NONVISUAL is an allowed M1 disposition for interaction/visual class; M3 must replace with captures.
