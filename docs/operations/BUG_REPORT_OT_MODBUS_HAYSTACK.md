# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-27  
**Platform:** `3.3.5+fa83c7245942` / `sha-fa83c72`  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)  
**Artifacts:** `reports/patch335_validate_233516/`

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-fa83c72` | tip publish success for `#791` | `fa83c7245942` | central `3.3.5+fa83c7245942` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-fa83c72` **linux/arm64** | same tip | `fa83c7245942` | fieldbus `/health` ok |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| Combined OT + synth (`combined_ot_synth_validate.sh`) | **PASS** (`combined_rc=0`) — BACnet 02, MQTT persist 03, Modbus 04, Haystack 05, synth CSV |
| Dual MQTT 600s (`10_dual_mqtt_signoff.sh`) | **PASS** (`dual_rc=0`, 16 passed / 1 skipped digests.txt) |
| BACnet pcap FP scan (`11_bacnet_pcap_fp_scan.sh`) | **PASS** (`pcap_rc=0`) — 33 ReadProperty, 0 Who-Is storm / ephemeral-broadcast findings |
| Dual edges + ingest growth | **PASS** — `fieldbus-1` (lab) + `pi-1` (bldg2) `has_telemetry:true`; ingest_ok 27→47 during soak |
| Weather | **PASS** — Madison (bench) / Chicago (Pi) |

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | linux/amd64 (bench) | **linux/arm64** (native) |
| Fieldbus tip | `sha-fa83c72` / `fa83c7245942` | `sha-fa83c72` / `fa83c7245942` |
| MQTTS numeric lines (600s peek) | 10 | 10 |
| Accumulation parity | ratio≥0.5 **PASS** (counts matched; see OPEN on timestamp span) | same |

Ops notes for soak (gitignored local only): `OPENFDD_SITE_ID=+` via `compose.cloudsim.local.yml`; bench OT `field_devices` from `field_devices.bench.example.toml`; optional `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` on both edges for denser 10‑minute accumulation.

## BACnet pcap

| Check | Result |
|------|--------|
| Capture tool | privileged docker `tcpdump` → pcap; decode via rusty-bacnet `bacnet capture --read … --decode` (host lacks passwordless sudo/`CAP_NET_RAW`) |
| Capture size | `ot_bench.pcap` ~10.6 KiB / 90s |
| Decode / FP scan vs bad_rusty_bacnet_app | **PASS** — `whois=0`, `read_property=33`, `ephemeral_whois=0`, findings `[]` |

## Open findings (future patch cycles)

| ID | Finding | Status |
|----|---------|--------|
| H10 | Large historian quals | **OPEN** |
| dependabot-thrift | Sticky Dependabot thrift updates fail on master | **OPEN** (non-product) |
| mqtt-span-parse | Dual MQTT parity `span_s=0` / `n_ts=0` (payload timestamps not parsed; count parity still green) | **OPEN** (gate hardening) |
| pcap-host-caps | Host `bacnet capture` / `tcpdump` need sudo or CAP_NET_RAW; gate uses privileged docker tcpdump | **OPEN** (ops; documented) |
| coderabbit-storage | Deferred package-ingest full `OPENFDD_STORAGE_URL` layout items if still open | **OPEN** |
| lint-sweep | Scoped `#[allow]`/`#[expect]` leftovers outside first hygiene pass | **OPEN** |

## Hygiene

- Patch-cycle train: blank → tip soak → fill this report. Agent law: [`openfdd_agent_spec/`](../../openfdd_agent_spec/) ([`docs/RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md)).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
- No stale PRs / feature branches after each tiny rev bump.
- Next product fix → bump `3.3.5` → `3.3.6`, wait GHCR, re-pin both hosts to the same `sha-*`.
