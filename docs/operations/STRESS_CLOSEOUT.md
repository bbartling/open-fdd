---
title: Stress closeout (nightly OT + Railway)
parent: Operations
nav_order: 6
---

# Stress closeout — agent handbook

Canonical **rigorous stress LAST** protocol after a product tip lands on GHCR. Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md). Next-rev template: [`PATCH_CYCLE.md`](PATCH_CYCLE.md).

**Do not claim a train CLOSED** with only merge + one spot gate. Cite tip-pin artifacts (not an older `sha-*` stress run).

Entry point + profiles: [`scripts/qualification/README.md`](../../scripts/qualification/README.md).

## Three execution tiers

| Tier | Where | What | Not |
|------|--------|------|-----|
| **Per PR** | GitHub Actions / unit harness | Contract tests, AppSec (`appsec.yml`), fault-injection unit gates | Deploy credentials, OT access for untrusted forks |
| **Isolated candidate** | Disposable CI / lab stack | Digest-pinned images, synthetic seed, **authenticated** ZAP AF + MQTT ACL fixtures, endurance/restore | Live Railway OT writes; claiming Railway PASS from local smoke |
| **Railway field** | Railway hub + bensbench x86 fieldbus | CSV fault matrix, expected-edge telemetry, public baseline ZAP, auth role matrix, Railway MCP↔REST | Active payload scans, DoS, Pi fieldbus, local `react-ot` head-end |

Prior closeouts that said “authenticated deep ZAP out of scope” remain true for the **Railway field** tier. Authenticated ZAP belongs in the **isolated candidate** tier (tooling may ship ahead of a green disposable run — mark `BLOCKED` with prerequisites, do not substitute).

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
| 0 | Hub + field + edges | gate `00_hub_health_edges` | Railway health `3.3.N+…`; fieldbus `:8081`; expected edge (or any) `has_telemetry:true` — **strict** probe chain |
| 0b | MQTTS → Overview charts | API overview/series + SPA Zone Other | Hosted-weather AV **9101** → role **`zone_t`**; **Zone Other** / MQTT generic zone charts populated (not empty with rising `ingest_ok`). Artifact or **DEFERRED** w/ operator-browser reason |
| 1 | Synthetic-59 | `--api-base` Railway | **59/59** (registry coverage reported separately when available) |
| 2 | Gate 17 | `RUN_SYNTH59_HEALTH_MATRIX=1` against Railway | health matrix + overview |
| 3 | B100 | `RAILWAY_ONLY=1` B100 spot | FC1 / runtime / series on Railway |
| 4 | Creekside | fixture + full zip | `LAKESIDE_ES` |
| 5 | Gate 19 | bundle validate | structural **READY** ≠ engineering/ML completeness |
| 6 | OWASP ZAP (light) | public `zap-baseline.py` + `zap_baseline_verdict.py` | High=0; Medium disposition explicit (`ACCEPT_ZAP_MEDIUM`); **not** authenticated AF |
| 7 | Auth role matrix | `scripts/qualification/auth_role_matrix.sh` | anon deny; admin/operator positive/deny per product contract |
| 8 | MCP accuracy | `railway_mcp_accuracy.sh` | exact `OPENFDD_MCP_IMAGE` sha-*; MCP↔REST parity; **no** local-central fallback |

### Truthful manifests (3.3.26+)

- Artifacts: `qualification_manifest.json` + generated `SUMMARY.md` under `reports/nightly-ot-bench_<TS>/`.
- Statuses: `PASS` | `FAIL` | `ERROR` | `SKIPPED` | `BLOCKED` | `NOT_APPLICABLE`.
- **`SKIP_ZAP=1` records `06_zap_baseline=SKIPPED` ⇒ not `fully_qualified`.** Do not emit a PASS sentence that claims ZAP ran.
- Missing/malformed ZAP JSON ⇒ `ERROR`.
- Mixed mqtt/fieldbus pins vs central/web tip ⇒ log hybrid compatibility; do not claim full-stack tip qualification.

### STRESS 6 notes (field ZAP — fluffy, not bug bounty)

- Target: public web origin only (SPA + `/api/health` / login). Operator-owned URL.
- Out of scope **on live hub:** authenticated deep crawl, MQTT/OT, DoS, activeScan against real buildings.
- In scope **isolated tier:** pinned ZAP AF plan, OpenAPI import, role contexts — see qualification README remaining blockers.
- Triage Low/Informational cookie noise in BUG_REPORT; fail-stop on High (and Medium unless explicitly accepted).

```bash
# Prefer the wrapper (records manifest + verdict parser):
./scripts/nightly-ot-bench/run_railway_hub_stress.sh

# Manual public baseline only (still parse JSON — do not trust -I alone):
ART="reports/zap-railway_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ART"
docker run --rm -v "$PWD/$ART:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t "$RAILWAY_PUBLIC_URL" -r zap_baseline.html -J zap_baseline.json -I
python3 scripts/qualification/zap_baseline_verdict.py --report "$ART/zap_baseline.json" --accept-medium
```

## Related product gates (3.3.20+)

| Gate | Purpose |
|------|---------|
| `scripts/gates/creekside_package_import_spot.sh` | Nested `openfdd_package_v1` + utilities wrapper |
| `scripts/nightly-ot-bench/19_engineering_bundle_validate.sh` | `openfdd_engineering_bundle_v1` structural validate |
| `scripts/openfdd_bundle_validate.py` | Offline bundle schema / READY |
| `scripts/qualification/*` | Manifest, ZAP verdict, auth matrix, Railway MCP |

Export / Dump UI: `/export` (nav label **Dump** after 3.3.22; alias `/wattlab`). Bundle API: `POST /api/jobs/{id}/exports`.  
Machine recreate: [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md). Patch trains: [`patch_trains/`](patch_trains/).

## After stress

1. Flesh BUG_REPORT verdict with **this tip’s** artifact paths + `fully_qualified` from the manifest (not prior train).
2. `SESSION_LOG` entry with paths.
3. GH hygiene END: 0 open PRs, only `master`, tip Actions green.
4. Never rewrite older PASS claims as if they came from the enhanced suite.

## Anti-patterns

- Claiming CLOSED after merge without Railway CSV + edges + ZAP on **this** tip pin.
- Citing an older `sha-*` stress run as proof for a newer tip.
- `SKIP_ZAP=1` (or missing ZAP JSON) while advertising a ZAP PASS.
- Scanning non-owned hosts with ZAP.
- Putting Raspberry Pi fieldbus / fake-device Pis back on the closeout path.
- Standing up local `react-ot` as the AFDD head-end for a patch cycle.
- Local `docker build` of central/web on low-RAM benches.
- Gate 13 local-central fallback presented as Railway MCP evidence.
