# Wave O — Known bugs / patch train tracker

**Ops pin (live Railway):** `sha-bdbd9c0` / **3.5.17** · `multi_tenant=true`
**Closed tips:** O8–O9 3.5.11 · O7 3.5.12 · O11+O12a 3.5.13 · O13 3.5.14 · O14 MQTT 3.5.15 · O1 write ACL 3.5.16 · **O6 historian limits 3.5.17**
**Next tip:** O2 audit/authz tests · O4 Mint residual

Parent plan: `.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`  
Prior Soft-OPEN: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)

## Bake order

O8 → O9 → O10 → O7 → O3 → O1 → O6 → O2 → O4 · **O5 Soft-OPEN only** (IdP/MFA)

**O2 expanded:** Kali/Railway multi-user shared-DB harden (permission matrix + server ACL + headers + tests) — see plan § O2 / [`wave_o2_…`](../../.cursor/plans/wave_o2_audit_zap_ce235993.plan.md).

| Step | Status | Evidence |
|------|--------|----------|
| O8 hub admin | **MERGED** #925 | `/admin` + `/api/admin/*` · gate 33 |
| O9 site data-model ACL | **MERGED** #925 | site export + session `building_id` ACL |
| O10 full HVAC @300s | **CLOSED** 3.5.15 | gate32 14→46; 35 HVAC equips in historian (hw_plant Soft — BIP .32); JCI°F+Trane°C |
| O7 Overview cache | **MERGED** #926 | silent per-`buildingId` cache · **3.5.12** |
| O11 PyPI Pages | **MERGED** #927 | `docs/ecm/` section + Drivers CSV nav dedupe |
| O12a Plotly PNG stems | **MERGED** #927 | 3.5.13 type stems |
| O12b Creekside meter map | OPEN | BAS BACnet electricity meter in dataset; data model lacks metering roles |
| O13 health post-repin | **MERGED** #928 | 3.5.14 started_at/uptime/historian_present |
| O14 MQTT packet / chunk | **CLOSED** 3.5.15 | rumqttc 1MiB + per-equip chunks |
| O1 import write ACL | **CLOSED** 3.5.16 | peek+deny foreign building; gate31 append 403 |
| O3 metric/MSTP | **CLOSED** ops | Trane ~21°C vs JCI ~70°F; distinct ZN-T/SAT across Trane VAVs |
| O6 historian limits | **CLOSED** #931 / 3.5.17 | retain_days+size_gib admin API/UI; import/MQTT enforce; FDD/analytics start clamp; gate31 PASS + gate32 99→134 on tip |
| O2a audit + ZAP disposition | **IN PR** 3.5.18 | gate 31 body ok:false + equip/analytics; gate 33 historian-limits + mass-assign; gate 34 headers/security.txt/CORS |
| O2b MT shared-DB harden | **IN PR** | security.txt nginx location; Auth redirect unit tests; stress required 22+23 |
| O4 Mint M5 | queued | after O2 |

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
