---
title: Fieldbus edge to MQTTS hub
parent: Operations
nav_order: 18
---

# Fieldbus edge → MQTTS cloud hub (generic pattern)

This is the **public** pattern for on-prem `openfdd-fieldbus` publishing into a Railway (or LAN) MQTTS hub. It does **not** include private site kits, IPs, or credentials.

## Topology

```text
[BACnet / Modbus OT LAN] → openfdd-fieldbus (on-prem) --MQTTS--> openfdd-mqtt → openfdd-central → openfdd-web
```

- **Never** run `openfdd-fieldbus` on Railway / public internet.
- Poll + publish = **fixed 300 s** (Wave N). Health-role subset (~30%) throttles MS/TP load.
- Multi-tenant hubs use topics: `openfdd/v1/tenants/{tid}/buildings/{bid}/edges/{eid}/telemetry/...`

## Operator steps (generic)

1. Provision an MQTT edge kit (`deploy/mqtt` tooling) for `{building}__{edge}` with TLS client certs + ACL limited to that tenant/building/edge.
2. Place kit + `field_devices.toml` + `gateway.toml` on the OT host (host networking for BACnet/IP).
3. Pull `ghcr.io/bbartling/openfdd-fieldbus:sha-<7>` (newest-by-created when matching hub).
4. Start compose; wait ≥ one 300 s poll; confirm central `/api/health` ingest counters / edges advance.
5. On each GHCR refresh: pull → recreate → one poll validate (see private site scripts — not in this repo).

## Local Mint / OptiPlex bench

Production OT on the bench is still **`openfdd-fieldbus` (rusty-bacnet)**. BACpypes3 is
diagnose-only (Who-Is / RP when fieldbus is stopped). See
[`LOCAL_BACNET_BACPYPE3_BENCH.md`](LOCAL_BACNET_BACPYPE3_BENCH.md) ·
`./scripts/ops/local_bacnet_ot_bench.sh`.

## Policy

Full agent rules: [`BACNET_OT_POLICY.md`](BACNET_OT_POLICY.md) · Wave N tracker: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md).
