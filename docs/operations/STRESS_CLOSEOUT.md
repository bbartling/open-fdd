---
title: Stress closeout (nightly OT + Railway)
parent: Operations
nav_order: 6
---

# Stress closeout — agent handbook

Canonical **rigorous stress LAST** protocol after a product tip lands on GHCR. Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md). Next-rev template: [`PATCH_CYCLE.md`](PATCH_CYCLE.md).

**Do not claim a train CLOSED** with only merge + one spot gate. Cite tip-pin artifacts (not an older `sha-*` stress run).

## Topology (3.3.20+)

| Role | Where | Purpose |
|------|--------|---------|
| **Hub** | Railway central + mqtt + web | AFDD / CSV / UI head-end |
| **Field** | bensbench **x86** `openfdd-fieldbus` only | MQTTS into Railway (`reseau.proxy.rlwy.net:44763`) |

Raspberry Pis are **out of** Open-FDD stress (bosspi / fake AHU `.13` / fake VAV `.14` freed). Do not stand up a local `react-ot` hub for patch-cycle closeout. Optional local `run_all` remains a lab recipe only.

## Bootstrap before stress

1. Tip Actions green + GHCR **Publish Open-FDD stack** success.
2. **Railway:** backup → re-pin central → mqtt → web — [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) · skill [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md).
3. **Field:** `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` (stops local react-ot; host-net fieldbus → Railway). Kit via `POST /api/mqtt/edge-kits` (`bldg2` / `bensbench-1`).
4. Then `./scripts/nightly-ot-bench/run_railway_hub_stress.sh`.

Low-RAM: never local `docker build`; no local central/web/mqtt on the closeout path.

## Stress matrix (fill BUG_REPORT)

| # | Name | Command / artifact | Pass |
|---|------|--------------------|------|
| 0 | Hub + field + edges | `run_railway_hub_stress.sh` prep | Railway health `3.3.N+…`; fieldbus `:8081`; `has_telemetry:true` |
| 1 | Synthetic-59 | `--api-base` Railway | **59/59** |
| 2 | Gate 17 | `RUN_SYNTH59_HEALTH_MATRIX=1` against Railway | health matrix + overview |
| 3 | B100 | `RAILWAY_ONLY=1 ./scripts/gates/railway_b100_parity_spot.sh` | FC1 / runtime / series on Railway |
| 4 | Creekside | `BASE=$RAILWAY` fixture + full zip | `LAKESIDE_ES` |
| 5 | Gate 19 | against Railway | validator **READY** |
| 6 | OWASP ZAP (light) | `zap-baseline.py` vs **Railway public HTTPS** | no unexplained High/Critical → `reports/zap-railway_<TS>/` |

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

- Claiming CLOSED after merge without Railway CSV + edges + ZAP on **this** tip pin.
- Citing an older `sha-*` stress run as proof for a newer tip.
- Scanning non-owned hosts with ZAP.
- Putting Raspberry Pi fieldbus / fake-device Pis back on the closeout path.
- Standing up local `react-ot` as the AFDD head-end for a patch cycle.
- Local `docker build` of central/web on low-RAM benches.
