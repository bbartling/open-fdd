---
name: Wave S MQTT Pause Parked
overview: "Parked feature — tenant-scoped edge telemetry pause/resume UI. Backend exists; not part of TTL tip."
todos:
  - id: pause-ui-later
    content: "Later wave: SPA pause/resume (client=own edges; admin=all) + audit; Option A streaming only"
    status: pending
isProject: false
---

# MQTT / edge telemetry pause-resume (parked)

**Parent:** [wave_soft_park_480c17e1.plan.md](wave_soft_park_480c17e1.plan.md)  
**Prior decision:** Wave P Option **A** — pause/resume **streaming**, do **not** stop the fieldbus container process.

## Already exists (backend)

- Fieldbus: `services/fieldbus/src/services/telemetry_control.rs`
- REST: `/telemetry/suspend`, `/telemetry/resume`, status
- MQTT command: `target_id=edge:telemetry` via Central `POST /api/commands`
- Ops can already issue commands

## Later feature wave (not now)

- Tenant-scoped MQTT / Ops dashboard switch
- Client JWT: only own edges; admin: all edges
- Audit events for suspend/resume
- Stress gate for pause → ingest stall → resume → ingest climbs

Do **not** implement in the Data Model TTL tip.
