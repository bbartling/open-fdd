# P2-M2 — Shadow comparison and soak qualification

## Shadow (P2-M2-01)

Harness: `scripts/phase2_shadow_compare.py`

Safety:
- Immutable inputs: `tests/react_parity/manifest.json` content hashes
- Comparison artifact: `docs/migration/react-rust/evidence/shadow/latest_shadow_report.json`
- **Does not** write production findings
- **Does not** invoke pandas / Streamlit as a request fallback

Comparisons:
1. Fixture directory hashes vs manifest (exact)
2. Rule-outcome categorical statuses (`pass` / `insufficient_data` / `error`) exact

Gate: `UNKNOWN` or any critical candidate defect → FAIL.

## Soak (P2-M2-02)

Exercise matrix (authorized synthetic / CI evidence):

| scenario | evidence | result |
|---|---|---|
| Repeated fixture / exporter stability | `tests/react_parity/test_fixtures_and_exporter.py` | PASS (CI) |
| Hostile upload | `hostile_zip` fixtures + package.rs / central tests | PASS (CI) |
| Auth expired / login | AuthPage vitest + `/api/auth/*` | PASS (unit) |
| Stale revision / job concurrency | jobs disposition revision tests | PASS (CI) |
| Compose restart topology | `compose.react.yml` config validate + ROLLBACK_DRILL | PASS (doc+CI) |
| Browser refresh sticky UI gen | cutover cookie tests in `cutover.rs` | PASS (unit) |
| Large / concurrent / retention | deferred to ops soak on canary cohort; no blocker for synthetic gate | SKIP → canary watch |
| Partial MQTT outage | no protocol change in this PR; fieldbus unchanged | N/A |

## Result

**PASS** for synthetic shadow gate at this commit. Next canary prerequisite:
recorded promotion decision (P2-M3) with Streamlit fallback still available;
minimum observation via migration metrics (`/api/ui/migration-metrics`).
