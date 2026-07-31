# Parity evidence log (P1-M0-02 seed / M1 updates)

| date | capability_id | fixture hash | source commit | engine versions | result | mismatch class | PR |
|------|---------------|--------------|---------------|-----------------|--------|----------------|-----|
| 2026-07-31 | CAP-PLOTS | `plotDataset` + ReportsPage vitest | branch `feat/p1-m5-b-plot-datasets` | Vitest | Series→figure contract; SVG host; gap counts | SEMANTIC+INTERACTION | P1-M5-B |
| 2026-07-31 | CAP-RULES | rule params API + RulesPage tuning/sliders vitest | branch `feat/p1-m5-a-rule-catalog-tuning` | Vitest | Bounds clamp; session-config params; aliases/parity in catalog | EXACT+INTERACTION | P1-M5-A |
| 2026-07-31 | CAP-RULES / results | `fddApi.test.ts` + RulesPage/FindingsPage vitest | branch `feat/p1-m4-04-fdd-run-results` | Vitest mocked `/api/fdd/*` | Registry run + result filter/download; cancel via AbortSignal | EXACT+INTERACTION | P1-M4-04 |
| 2026-07-31 | CAP-MAP | mapping inventory unit + `mappingApi.test.ts` / `MappingPage.test.tsx` | branch `feat/p1-m4-03-mapping-validation` | Vitest + edge unit tests | Unmapped/ambiguous blockers; VAV parent heuristic; session-config save; manifest download | EXACT+INTERACTION | P1-M4-03 |
| 2026-07-31 | CAP-UPLOAD | `package.rs` hostile_zip unit tests + `uploadApi.test.ts` / `UploadPage.test.tsx` | branch `feat/p1-m4-02-upload-hostile-zip` | Vitest + edge unit tests | Traversal/symlink/ratio rejects; multipart upload UX | SECURITY+INTERACTION | P1-M4-02 |
| 2026-07-31 | CAP-JOBS | `jobsApi.test.ts` + `JobsPage.test.tsx` | branch `feat/p1-m4-01-jobs-crud` | Vitest mocked `/api/jobs*` | List/create/patch/archive/restore/duplicate + revision conflict UX | INTERACTION | P1-M4-01 |
| 2026-07-31 | CAP-ERRORS / session | SESSION_TRANSLATION.md + session tests | branch `feat/p1-m3-03-routing-session` | React Router URL state | Deep-link/back for job/eq/wl; drafts non-authoritative | INTERACTION | P1-M3-03 |
| 2026-07-31 | CAP-WIDGETS / shell | `widgets.test.tsx` + HomePage gallery | branch `feat/p1-m3-02-widget-primitives` | Vite React shell | Controlled widgets + keyboard/a11y baseline; Plotly host placeholder only | INTERACTION | P1-M3-02 |
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
