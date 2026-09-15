# Wave O — Known bugs / patch train tracker

**Ops pin (live Railway):** `sha-e8f4fd3` / **3.5.14** · `multi_tenant=true` · O13 health fields live  
**Ops pin tip:** `sha-b029503` / **3.5.15** (O14)
**O1 tip (open):** **3.5.16** — package import write ACL — MQTT packet size + per-equipment publish chunks (O10 ACME unblock)

Parent plan: `.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`  
Prior Soft-OPEN: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)

## Bake order

O8 → O9 → O10 → O7 → O3 → O1 → O6 → O2 → O4 · **O5 Soft-OPEN only** (IdP/MFA)

**O2 expanded:** Kali/Railway multi-user shared-DB harden (permission matrix + server ACL + headers + tests) — see plan § O2 / [`wave_o2_…`](../../.cursor/plans/wave_o2_audit_zap_ce235993.plan.md).

| Step | Status | Evidence |
|------|--------|----------|
| O8 hub admin | **MERGED** #925 | `/admin` + `/api/admin/*` · gate 33 |
| O9 site data-model ACL | **MERGED** #925 | site export + session `building_id` ACL |
| O10 full HVAC @300s | **BLOCKED→fixing 3.5.15** | ACME catalog 36 HVAC @300s on `sha-e8f4fd3`; publish failed rumqttc 10KiB cap (~20KiB envelope) |
| O7 Overview cache | **MERGED** #926 | silent per-`buildingId` cache · **3.5.12** |
| O11 PyPI Pages | **MERGED** #927 | `docs/ecm/` section + Drivers CSV nav dedupe |
| O12a Plotly PNG stems | **MERGED** #927 | 3.5.13 type stems |
| O12b Creekside meter map | OPEN | BAS BACnet electricity meter in dataset; data model lacks metering roles |
| O13 health post-repin | **MERGED** #928 | 3.5.14 started_at/uptime/historian_present |
| O14 MQTT packet / chunk | **IN PR** | rumqttc 1MiB + per-equip envelopes + mosquitto `max_packet_size` |
| O2a audit + ZAP disposition | queued | **this agent:** audit asserts · **Kali agent:** ZAP/AF (cite only) |
| O2b MT shared-DB harden | **IN PLAN** | product ACL/headers + **beefed CI/stress tests** (no Kali here) |
| O3–O4 | queued | after O10 streams healthy |

## Hygiene

- 0 open PRs after each merge (except the active tip PR)
- Delete feature branches; tip Actions green before Railway re-pin
- Product OT = `openfdd-fieldbus` + rusty-bacnet; bacpypes3 diagnose-only

## Open defects (Wave O additions)

| ID | Status | Summary |
|----|--------|---------|
| **wave-o-plotly-newplot** | **CLOSED** 3.5.13 | RCx hosts downloaded `newplot.png`; PlotlyHost always stems + RCx/FDD type names |
| **wave-o-creekside-meter-map** | OPEN | `LAKESIDE_ES` / Creekside: integrated BAS BACnet electricity meter present in data; package map omits metering → empty Metering UI |
| **wave-o-health-post-repin** | **CLOSED** 3.5.14 | `/api/health` started_at/uptime/last_ingest_at/historian_present; gate 32 boot grace |
| **wave-o10-mqtt-packet-cap** | Patching **3.5.15** (hub+ACME tip live) |
| **wave-o1-import-write-acl** | Patching **3.5.16** | Full HVAC cell publish ~19.5KiB > rumqttc default 10KiB → eventloop tear-down; no Railway ingest advance |
