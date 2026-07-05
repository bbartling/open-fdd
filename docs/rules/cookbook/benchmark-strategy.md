---
title: Benchmark & regression strategy
parent: Rule Cookbook
nav_order: 9
---

# Benchmark and regression strategy

Public, reproducible validation for cookbook rules — no proprietary datasets required.

## Goals

1. **Parity** — SQL and Pandas produce identical `fault_raw` for the same input window
2. **Regression** — rule changes do not silently alter confirmed fault counts
3. **Coverage** — every nontrivial rule has ≥4 validation scenarios

---

## Data sources (public)

| Source | Use |
|--------|-----|
| Berkeley Lab FDD benchmark datasets | Fault signature shapes, taxonomy cross-check |
| ASHRAE GL36 public AFDD variable definitions | Threshold sanity, delay defaults |
| Synthetic `telemetry_pivot` fixtures | Deterministic CI — generated in-repo |
| Edge `POST /api/fdd/inject-scenario` | Live stack scenario injection before plant rules |
| Site historian exports (operator) | Production validation — not committed |

---

## Scenario taxonomy (per rule)

| Scenario ID | Description |
|-------------|-------------|
| `normal` | No fault — rule must stay false |
| `obvious_fault` | Clear violation — rule must latch after confirmation |
| `borderline` | Just inside/outside threshold — documents sensitivity |
| `missing_point` | Required column NULL — rule must stay false |
| `bad_sensor` | Out of range / flatline — gated by sensor quality macro |
| `wrong_units` | Values 10× expected — optional heuristic (SV-7) |

---

## Synthetic fixture format

```json
{"timestamp":"2026-07-01T12:00:00Z","equipment_id":"equip:test-ahu","oa_t":75.0,"sat":55.0,"sat_sp":55.0,"fan_cmd":1.0,"fan_status":true}
```

Store under `docs/rules/cookbook/fixtures/` (excluded from GitHub Pages).

Run offline:

```bash
python3 scripts/cookbook_parity_check.py --all
```

CI: `.github/workflows/cookbook-parity.yml`

---

## Parity regression procedure

```bash
# 1. Edge SQL test
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/TEST/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -d @scenario.json | jq '.rows[] | select(.fault_raw==true) | .timestamp'

# 2. Offline Pandas (analyst)
python scripts/cookbook_parity_check.py --rule RESET-1 --fixture fixtures/reset1_obvious.jsonl
```

Planned CI job: load fixture → compile rule SQL → compare against golden `fault_raw` bitmap.

---

## KPI scoring (KPI-1 advisory)

Aggregate confirmed faults by taxonomy family over a rolling 7-day window:

```
score = w1*economizer + w2*reset + w3*schedule + w4*plant_dt + w5*sensor_quality
```

Weights are site-tunable defaults — advisory only, not a vendor score.

---

## Release checklist

- [ ] Parity matrix updated for new/changed rules
- [ ] Gap matrix reflects new coverage
- [ ] Both cookbooks updated in same commit
- [ ] At least one synthetic scenario per new rule
- [ ] GitHub Pages deploy green
