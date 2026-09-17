---
name: Wave S MQTT Pause Parked
overview: "Edge telemetry pause/resume UI + required stress gate (Option A streaming only)."
todos:
  - id: pause-ui-later
    content: "Tenant-scoped audit polish; hub admin vs client edges — core UI + gate landed in Wave UX Soft Tip A"
    status: pending
isProject: false
---

# MQTT / edge telemetry pause-resume

**Parent:** [wave_soft_park_480c17e1.plan.md](wave_soft_park_480c17e1.plan.md)  
**Decision:** Wave P Option **A** — pause/resume **streaming**, do **not** stop the fieldbus container process.

## Backend

- Fieldbus: `services/fieldbus/src/services/telemetry_control.rs`
- REST: `/telemetry/suspend`, `/telemetry/resume`, status
- MQTT command: `target_id=edge:telemetry` via Central `POST /api/commands`
- Multi-tenant ON: `GET /api/edges` and `POST /api/commands` enforce `allow_building` on `site_id` (non–hub-admin sees own buildings only)

## Ops UI

- Operations → **Suspend telemetry**: edge picker from `GET /api/edges` (table + manual override); commands use `edge:telemetry` only.

## Stress qualification (required)

- Gate script: `scripts/nightly-ot-bench/35_mqtt_telemetry_pause_resume.sh`
- **Local OT:** `run_all.sh` runs phase **35** immediately after **03** MQTT persist (pause → stall → resume).
- **Railway hub stress:** `run_railway_hub_stress.sh` records **35_mqtt_telemetry_pause_resume** as a **required** gate after continuity (21) and capacity (24/24b). `MQTT_PAUSE_RESUME=0` skips (not fully qualified).

Do **not** fold this into the Data Model TTL tip alone — it is a cross-cutting OT + hub qualification gate.
