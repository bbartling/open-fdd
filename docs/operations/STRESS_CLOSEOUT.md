---
title: Stress closeout (nightly OT + Railway)
parent: Operations
nav_order: 6
---

# Stress closeout — agent handbook

Canonical **rigorous stress LAST** protocol after a product tip lands on GHCR. Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md). Plan example: `.cursor/plans/3.3.20_engineering_ml_bundle_utilities.plan.md`.

**Do not claim a train CLOSED** with only merge + one spot gate. Cite tip-pin artifacts (not an older `sha-*` stress run).

## Dual pipeline (never cross-wire for parity)

| Pipeline | Where | Purpose |
|----------|--------|---------|
| **A Cloud** | bosspi fieldbus → Railway mqtt → Railway central/web | Live OT MQTTS hub |
| **B Local** | bensbench `react-ot` GHCR pull | Firewall / on-prem dashboard + OT soak |

Same tip `sha-<7>` both sides. Do **not** point bosspi at local mqtt (or bench edge at Railway) during the parity gate.

## Bootstrap before stress

1. Tip Actions green + GHCR **Publish Open-FDD stack** success for tip (or accept product `sha-*` if hotfix is harness-only).
2. **Railway:** backup → re-pin central → mqtt → web — [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) · skill [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md).
3. **Local:** `./scripts/openfdd_maint_update_resume.sh react-ot sha-<7> --skip-maintenance` — [`LOCAL_DEPLOYMENT.md`](LOCAL_DEPLOYMENT.md). **Plain HTTP** (`:3000`/`:8080`) sends passwords and Bearer JWTs in the clear — **trusted/isolated LAN or VPN only**. For shared or untrusted networks, put a TLS-terminating reverse proxy in front (not shipped in default `react-ot`).
4. **bosspi:** fieldbus arm64 same `sha-*`; 60s poll+publish; Pipeline A `/api/edges` check.
5. Smoke 01 / 06 / 10 / 18 + Pipeline A, **then** stress.

Low-RAM: never local `docker build` for stack images; `WEATHER_SOAK_SECS=120`; `unset SKIP_PULL` on full `run_all`.

## Stress matrix (fill BUG_REPORT)

| # | Name | Command / artifact | Pass |
|---|------|--------------------|------|
| Prep | Smoke + Pipeline A | gates `01`/`06`/`10`/`18`; `/api/edges` | health OK; telemetry present |
| 1 | `run_all` | `unset SKIP_PULL`; `WEATHER_SOAK_SECS=120`; `./scripts/nightly-ot-bench/run_all.sh` | gates **00–16** PASS → `reports/nightly-ot-bench_<TS>/` |
| 2 | Synthetic-59 soak | `python3 scripts/synthetic_59_target_pair_soak.py --side ofdd` (from repo root) | **59/59** → `reports/wattlab-parity/artifacts/synthetic_59/` |
| 3 | Gate 17 | `RUN_SYNTH59_HEALTH_MATRIX=1 ./scripts/nightly-ot-bench/17_synthetic_health_matrix_fault_hours.sh` | health matrix + overview analytics PASS |
| 4 | B100 parity | `./scripts/gates/railway_b100_parity_spot.sh` | local ≡ Railway within tolerance → `reports/railway-b100-parity_<TS>/` |
| 5 | Creekside | `./scripts/gates/creekside_package_import_spot.sh` (+ full zip if available) | nested import PASS; utilities preferred |
| 6 | Gate 19 bundle | `./scripts/nightly-ot-bench/19_engineering_bundle_validate.sh` | validator **READY** |
| 7 | OWASP ZAP (light) | Docker `zap-baseline.py` vs **Railway public HTTPS URL only** | No unexplained High/Critical; HTML/JSON under `reports/zap-railway_<TS>/` |

### STRESS 7 notes (fluffy, not bug bounty)

- Target: public web origin only (SPA + `/api/health` / login). Operator-owned URL.
- Out of scope: authenticated deep crawl, MQTT/OT, DoS, permanent CI ZAP gate.
- Triage Low/Informational cookie noise in BUG_REPORT; fail-stop only on clear public High/Critical.
- Example:

```bash
ART="reports/zap-railway_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ART"
docker run --rm -v "$PWD/$ART:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t "$RAILWAY_PUBLIC_URL" -r zap_baseline.html -J zap_baseline.json -I
```

## Related product gates (3.3.20+)

| Gate | Purpose |
|------|---------|
| `scripts/gates/creekside_package_import_spot.sh` | Nested `openfdd_package_v1` + utilities wrapper |
| `scripts/nightly-ot-bench/19_engineering_bundle_validate.sh` | `openfdd_engineering_bundle_v1` structural validate |
| `scripts/openfdd_bundle_validate.py` | Offline bundle schema / READY |

Export UI: `/export` (alias `/wattlab`). Bundle API: `POST /api/jobs/{id}/exports`.

## After stress

1. Flesh BUG_REPORT verdict with **this tip’s** artifact paths (not prior train).
2. `SESSION_LOG` entry with paths.
3. GH hygiene END: 0 open PRs, only `master`, tip Actions green.

## Anti-patterns

- Claiming CLOSED after merge without `run_all` / synth59 / B100 on tip pin.
- Citing `sha-b565d78` stress as proof for a newer tip.
- Scanning non-owned hosts with ZAP.
- Cross-wiring Pipeline A and B for “parity.”
- Local `docker build` of central/web on low-RAM benches.
