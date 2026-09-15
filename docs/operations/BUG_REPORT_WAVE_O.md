# Wave O — Known bugs / patch train tracker

**Ops pin (live Railway):** `sha-f25ffcc` / **3.5.19** · `multi_tenant=true` (O12b tip **3.5.20** in flight)
**Closed tips:** … · O6 3.5.17 · O2 gates+security.txt 3.5.18 · **O2 nginx header fix 3.5.19**
**Next tip:** O12b Creekside meter / utilities→fuel · O4 Soft-OPEN · O5 Soft-OPEN

Parent plan: `.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`  
Prior Soft-OPEN: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)

## Bake order

O8 → O9 → O10 → O7 → O3 → O1 → O6 → O2 → O4 · **O5 Soft-OPEN only** (IdP/MFA)

| Step | Status | Evidence |
|------|--------|----------|
| O8 hub admin | **MERGED** #925 | `/admin` + `/api/admin/*` · gate 33 |
| O9 site data-model ACL | **MERGED** #925 | site export + session `building_id` ACL |
| O10 full HVAC @300s | **CLOSED** 3.5.15 | gate32 14→46; 35 HVAC equips (hw_plant Soft) |
| O7 Overview cache | **MERGED** #926 | 3.5.12 |
| O11 PyPI Pages | **MERGED** #927 | `docs/ecm/` |
| O12a Plotly PNG stems | **MERGED** #927 | 3.5.13 |
| O12b Creekside meter map | **PATCHING 3.5.20** | RCx `meter_elec_cdd` → `CS_ELEC_METER` (12 months); fuel campus from `utilities_v1`; stamp `equipType: meter`; Data Model merges historian-only equips |
| O13 health post-repin | **MERGED** #928 | 3.5.14 |
| O14 MQTT packet / chunk | **CLOSED** 3.5.15 | rumqttc 1MiB + chunks |
| O1 import write ACL | **CLOSED** 3.5.16 | gate31 append 403 |
| O3 metric/MSTP | **CLOSED** ops | Trane °C vs JCI °F |
| O6 historian limits | **CLOSED** #931 / 3.5.17 | gate31 + gate32 99→134 |
| O2 authz + security.txt | **CLOSED** #932/#933 / 3.5.19 | gates 31/33/34 PASS; headers live; gate32 165→231 on 3.5.18 |
| O4 Mint M5 | **Soft-OPEN** | tip `sha-f25ffcc` / 3.5.19 gates 31/33/34 PASS; full hub stress not fully_qualified — synth59 handoff zip missing on Mint |
| O5 Stage C IdP/MFA | Soft-OPEN | commercial |

## Hygiene

- 0 open PRs after each merge (except the active tip PR)
- Delete feature branches; tip Actions green before Railway re-pin
- Product OT = `openfdd-fieldbus` + rusty-bacnet; bacpypes3 diagnose-only

## Open defects (Wave O additions)

| ID | Status | Summary |
|----|--------|---------|
| **wave-o-plotly-newplot** | **CLOSED** 3.5.13 | RCx hosts downloaded `newplot.png`; PlotlyHost always stems + RCx/FDD type names |
| **wave-o-creekside-meter-map** | **PATCHING 3.5.20** | `LAKESIDE_ES`: BAS `CS_ELEC_METER` (`elec_power`) present; package map was AHU-only + utilities not promoted to fuel campus → empty Metering UI. Fix: meter type stamp, historian merge into Data Model mapping, package utilities→fuel campus sync, `billing_period` bill parse |
| **wave-o-health-post-repin** | **CLOSED** 3.5.14 | `/api/health` started_at/uptime/last_ingest_at/historian_present; gate 32 boot grace |
| **wave-o10-mqtt-packet-cap** | **CLOSED** 3.5.15 | Full HVAC cell publish ~19.5KiB > rumqttc default 10KiB → eventloop tear-down |
| **wave-o1-import-write-acl** | **CLOSED** 3.5.16 | Package import/append deny foreign building when MT ON |
