# Stage 4 auto-completion plan

**Branch:** `stage4-finish-parity-and-tuning`  
**Baseline:** 314 pass / 54 fail / 11 skipped @ 0.5h (`b93a929` / reconciled `7eda12b`)  
**Goal:** Runnable analyst dashboard + close parity gaps + complete SQL tuning — without deleting pandas or starting React.

---

## Phase 0 — Runnable dashboard (immediate)

| task | status | notes |
| --- | --- | --- |
| `.env` + data paths | ✅ local BUILDING_100 + parquet cache | validate_data GO on OneDrive path; repo `./data` also present |
| Start FastAPI full mode | ✅ | `VIBE19_RUST_CACHE=1 uvicorn asgi:app --port 5000` (PID on 127.0.0.1:5000) |
| Engineer login | default PIN `vibe-coder` unless `ENGINEER_PIN` set | header chip on every page |
| Smoke URLs | `/index.html`, `/docs`, `/api/sql-rules`, `/api/cookbook/catalog` | cookbook + SQL tuning panel |
| Warmup | Rust parquet optional on startup | first charts may take ~30s |

**Login:** http://127.0.0.1:5000/index.html → Engineer PIN `vibe-coder` (default)

---

## Phase 1 — Parity P0 (OAT-METEO + ECON-4)

### OAT-METEO (max Δ 32.7h)

1. Dump Python oracle samples: `debug_rule_parity.py --rule OAT-METEO --equipment AHU_2`
2. Compare timestamp join: Python `merge(weather, how="left")` vs SQL LEFT JOIN on `timestamp_utc`
3. Fix fault_pct denominator: full AHU timeline (Python `total_hours = len(df)`)
4. Audit weather staging timezone (America/Chicago) vs Parquet nanoseconds
5. Add Rust/Python fixture tests (missing wx row, null wx, confirm boundary)
6. **DoD:** max Δ ≤ 0.5h per AHU or documented blocker

### ECON-4 (max Δ 26h)

1. Confirm CTE present (done) — verify streak matches `confirm_fault(600s)`
2. Compare OA fraction: `(mat-rat)/(oa_t-rat)*100` vs Python; NULL when `oa_t==rat`
3. Fan gate: Python `_fan()` vs SQL `fan_cmd` only — add `fan_status` fallback in SQL if needed
4. Sample dump AHU_1 → `.cache/debug/econ4_ahu1.json`
5. **DoD:** max Δ ≤ 0.5h

---

## Phase 2 — Parity P1 (FC8, FC13, FC10, FC2, FC9, FC12, ECON-2)

For each rule:
- Side-by-side Python `fcN()` vs SQL threshold literals
- `debug_rule_parity.py` on worst AHU
- Fixture: threshold boundary ±ε, confirm boundary (599s vs 600s @ 300s poll)
- Move constants to `registry.yaml` placeholders

| rule | key constants |
| --- | --- |
| FC8 | DELTA_SUPPLY_FAN, sqrt(SUPPLY_TOL²+MIX_TOL²), AHU_MIN_OA_DPR |
| FC13 | SAT_ERR, CLG_VALVE_MIN, OA damper gates |
| FC10 | MIX_TOL sqrt(2), clg>0.01, econ>0.9 |
| FC2 | MIX_TOL, min(rat, oa_t) envelope |
| FC9 | MIX_TOL, DELTA_SUPPLY_FAN, economizer gates |
| FC12 | SUPPLY_TOL, MIX_TOL, damper OR gate |
| ECON-2 | oat_hi 63, damper 0.42 |

**DoD:** material mismatch list empty @ 0.5h OR each residual has exact sample-level explanation

---

## Phase 3 — VAV-1 residuals (34 × Δ < 7h)

- Confirm 900s / CONFIRM_ROWS=3
- Comfort band inclusive bounds (68–76°F)
- Per-VAV zone_t ranking spot-check (VAVFC_100, VAVH_115)
- **DoD:** max VAV-1 Δ ≤ 0.5h

---

## Phase 4 — SQL tuning completeness

| task | status |
| --- | --- |
| `parameters:` for all 19 rules in `registry.yaml` | partial (5/19) |
| Rust merge/clamp/reject unknown | ✅ |
| Per-request preview via Rust CLI | ❌ (batch cache only) |
| `GET/POST /api/sql-rules*` | ✅ |
| Static SQL tuning panel | ✅ basic |
| Save profile YAML | ✅ |

Add to every rule: `confirm_seconds` + rule-specific thresholds + `scope_allowed`.

---

## Phase 5 — Docs + CI truth

Update after each parity win:
- `RUST_DATAFUSION_PARITY_BENCHMARK.md`
- `SESSION_LOG.md`, `BUILD_CHECKPOINTS.md`
- `PYTHON_REDUCTION_PLAN.md` (classify keep/delete-after-wiring)

Tests each iteration:
- `cargo test`, `cargo clippy`
- `pytest -q` (local; fix Windows PermissionError separately)
- Full compare pipeline

---

## Phase 6 — Merge policy

- Work on `stage4-finish-parity-and-tuning`
- Merge to `develop` when: app smoke passes + at least one P0 rule proven + no regressions on zone analytics
- **Never** delete pandas paths until dashboard uses SQL preview for wired rules

---

## Definition of complete

Stage 4 is **complete** when all of:

1. Dashboard runs locally with login, cookbook sliders, SQL tuning panel
2. 19/19 SQL rules execute
3. Material mismatch empty @ 0.5h (or each item in blocked list with evidence)
4. Full registry parameterization
5. Docs + benchmark current
6. Merged to `develop`

**Current status:** Phase 0 complete (app running); Phases 1–6 in auto-iteration.

**Live smoke (2026-07-09):** `/health` OK · `/api/sql-rules` 19 rules + rust cache · `/api/cookbook/catalog` 50 rules · `/index.html` 200
