# Wave M — AFDD flood gate (community how-to)

Budgeted multi-rule AFDD load/correctness gate for enhanced qualification (M5 gate 12 / stress gate 19).

## Defaults

- **Primary target:** isolated tip compose / disposable candidate
- **Standalone script** refuses live Railway unless `OPENFDD_AFDD_FLOOD_ALLOW_LIVE=1`
- **`run_railway_hub_stress.sh`** sets ALLOW_LIVE=1 because that parent script is already an authorized ops window (same class as ZAP)

## Budgets (FAIL if exceeded — do not silent-trim)

| Budget | Env | Default |
|--------|-----|---------|
| Max wall clock | `OPENFDD_AFDD_FLOOD_MAX_WALL_SECS` | 900 |
| Max rules | `OPENFDD_AFDD_FLOOD_MAX_RULES` | 80 |
| Fixture | `OPENFDD_AFDD_FLOOD_FIXTURE` | Synthetic-59 |
| Building | `OPENFDD_AFDD_FLOOD_BUILDING` | SYNTHETIC_59 |

Never drop expected faults to go green. BUILDING_50 remains deferred (separate package-on-bench).

## Local / CI

```bash
cd ~/open-fdd
# Against tip compose central:
CENTRAL_BASE=http://127.0.0.1:8080 \
  ./scripts/nightly-ot-bench/2N_wave_m_afdd_flood.sh
```

## Disposable Railway candidate

```bash
export OPENFDD_API_BASE=https://<disposable-hub>
export OPENFDD_ADMIN_PASSWORD=...   # never commit
export OPENFDD_AFDD_FLOOD_ALLOW_LIVE=1
./scripts/nightly-ot-bench/2N_wave_m_afdd_flood.sh
```

Artifacts: `2N_wave_m_afdd_flood.json` + `.md` under the artifact dir.

## Honesty

Flood must go through durable AFDD (`/api/afdd/scheduler/run-now`) with `/api/fdd/run` fallback — not browser mash. Partial/fail rules fail the gate.
