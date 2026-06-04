---
title: BACnet driver capabilities
parent: BACnet
nav_order: 1
---

# BACnet driver capabilities

Open-FDD BACnet I/O lives in **`bacnet_toolshed/`** (BACpypes3) and two edge containers:

| Component | Where | Role |
|-----------|--------|------|
| **`openfdd-commission`** | `:8767` | Discovery jobs, read/write, priority-array, poll loop trigger |
| **`openfdd-bacnet-poll`** | host network | Scheduled RPM poll → `workspace/bacnet/polls/samples.csv` |
| **`openfdd-bridge`** | `:8765` | REST proxy, driver CSV registry, model import, feather ingest |

Stack args come from **`workspace/bacnet/commissioning/commission.env`** (`BACNET_BIND`, `ROUTER_IP`, `MSTP_NET`, …). See [Getting started — BACnet bind](../getting_started#3-bacnet-lab-bind-see-devices-on-ot-nic).

---

## Summary matrix

| BACnet capability | Status | How |
|-------------------|--------|-----|
| **Who-Is / I-Am** | Supported | `POST /api/bacnet/whois`, CLI `discover_devices`, commission agent |
| **Device discovery (inventory)** | Supported | Who-Is → device address, vendor, description |
| **Object-list read** | Supported | Full list or segmented `object-list` if device aborts |
| **Point discovery** | Supported | Per device: OID + `object-name` + **commandable** flag |
| **Full discover → CSV** | Supported | Job writes `points_discovered.csv` (`object-name`, `description`, `present-value`, `units`) |
| **ReadProperty** | Supported | Any valid `property_identifier` on one object |
| **ReadPropertyMultiple (RPM)** | Supported | Chunked (≈25 props/request); poll uses RPM for `present-value` |
| **Read priority-array** | Supported | Per commandable point; full 16-slot decode |
| **Supervisory / override scan** | Supported | All commandable points → active priority slots |
| **WriteProperty** | Supported (gated) | Priority **required**; `value: null` = **release** at that priority |
| **WritePropertyMultiple** | Not supported | Use repeated write or single RPM read |
| **COV subscribe** | Not supported | Use periodic poll |
| **ReadRange** | Not supported | — |
| **ReinitializeDevice / DM** | Not supported | — |
| **File object / backup** | Not supported | — |
| **BBMD registration** | Not built-in | Bind correct OT NIC/IP; use `--route-aware` for MSTP via IP router |
| **Alarm / Event enrollment** | Not supported | FDD uses historian + rules, not BACnet alarm ack |

---

## Discovery

### Who-Is / device scan

- Instance range: `DISCOVER_LOW` … `DISCOVER_HIGH` (env or API body).
- **BACnet/IP** broadcast on bound NIC.
- **MS/TP via router:** `ROUTER_IP` + `MSTP_NET` → Who-Is on `network:*@router` (see `discover_lib.collect_i_ams`).
- Returns I-Am fields: device identifier, address, description/object-name, max APDU, segmentation, vendor id.

### Point discovery (one device)

`POST /api/bacnet/point-discovery` → reads **object-list**, RPM **`object-name`** for all points, RPM **`priority-array`** on commandable types (AO/AV/BO/BV/MSO/MSV/integer-value, …) to set `commandable: true/false`.

### Full discover job

`POST /api/bacnet/discover` (or commission `POST /api/jobs/discover`) runs CLI `bacnet_toolshed.discover` → **`points_discovered.csv`**.

Per-point properties during discover:

- `object-name`, `description`, `present-value`, `units` (best-effort; skips on error)

Bridge: `GET /api/bacnet/inventory` groups CSV by device.

---

## Read path

| Operation | API / CLI | Notes |
|-----------|-----------|--------|
| Single property | `POST /api/bacnet/read` | Resolves device via cache or Who-Is |
| Multiple properties | `POST /api/bacnet/read-multiple` | List of `(object_identifier, property_identifier)` |
| Priority array | `POST /api/bacnet/priority-array` | All 16 slots with type + value |
| Supervisory check | `POST /api/bacnet/supervisory-check` | Override summary across commandable points |

Encoding: atomic/sequence/array → JSON-friendly values (`bacnet_ops.encode_rpm_value`).

---

## Write path

| Operation | API | Notes |
|-----------|-----|--------|
| **Write present-value (or other prop)** | `POST /api/bacnet/write` | `property_identifier` must be valid BACnet property id |
| **Release (relinquish)** | Same, `value: null` | **Requires** `priority` 1–16; writes BACnet `NULL` at that priority |
| **Priority on write** | Required | 1 = manual override … 16 = default |

**Safety gates (bridge):**

- `OFDD_ENABLE_BACNET_WRITE=1` or writes return **403**
- Optional `workspace/bacnet/write_allowlist.json` — `device_instances` and/or `object_identifiers`
- Role **`integrator`** for write; commission/operator for reads
- Audit log on denied writes

**Not supported:** write without priority, WritePropertyMultiple, confirmed COV, out-of-service manipulation APIs.

---

## Poll driver (historian)

| Item | Detail |
|------|--------|
| **Property** | **`present-value` only** (RPM per device) |
| **Intervals** | 60, 300, 600, 900 seconds per point (`points.csv` `poll_interval_s`) |
| **Output** | `workspace/bacnet/polls/samples.csv` (long format) |
| **Ingest** | `POST /api/bacnet/poll/once` or internal ingest → **feather** wide frames (Arrow IPC; compaction deferred — see [Arrow data plane](../architecture/arrow_data_plane.md)) |
| **Network** | Poll container **`network_mode: host`** (same UDP bind semantics as commission) |

Enable points: `bacnet_toolshed.enable_points` or bridge `PATCH /api/bacnet/driver/point`, `merge-rows`, driver tree UI.

---

## Point mapping & BRICK model

| Step | Mechanism |
|------|-----------|
| Discovered rows | `points_discovered.csv` — BACnet oid, names, optional `brick_class` / `brick_tag` columns |
| Poll list | `points.csv` — `enabled=1`, `point_id`, `series_id`, site/building/system ids |
| Driver registry | Bridge `GET /api/bacnet/driver/tree` — devices/points, poll toggles, remap |
| Model merge | `POST /api/bacnet/import-to-model`, `POST /api/bacnet/driver/sync-discovery` |
| Rule bindings | `fdd_input` on BRICK points → Rule Lab `column_map` at FDD run |

**Driver maintenance APIs:** merge rows, enable/disable poll per point or device, remap instance/address, delete point/device, clear registry (+ model sync).

---

## Local BACnet server points (edge identity)

Commission agent exposes read-only **BV/AV** on the edge device instance (`server_points.py`): edge online, commission OK, poll row count, devices discovered, **active FDD fault count** — for BACnet supervisors that read the head-end.

The local BACnet **Device** defaults to object name **`OpenFDD`** and instance **`599999`**. Set per deployment in Ansible `host_vars` (`bacnet_device_name`, `bacnet_instance_id`) or `workspace/bacnet/commissioning/commission.env` (`BACNET_NAME`, `BACNET_INSTANCE`). Environment overrides: `OFDD_BACNET_DEVICE_NAME`, `OFDD_BACNET_INSTANCE`.

`GET /api/bacnet/server/points` returns the snapshot.

---

## Network / bind checklist

| Setting | Purpose |
|---------|---------|
| `BACNET_BIND` | `ip/mask:47808` — OT interface (required) |
| `BACNET_NAME` / `BACNET_INSTANCE` | Local virtual device (default **OpenFDD** / **599999**) |
| `OFDD_BACNET_DEVICE_NAME` / `OFDD_BACNET_INSTANCE` | Optional env overrides (Docker/systemd) |
| `ROUTER_IP` + `MSTP_NET` + `--route-aware` | MS/TP behind IP router |
| `DISCOVER_TIMEOUT` | Who-Is / discover wait (seconds) |
| Host network poll | Poll image must share host routing to reach `device_address` |

CLI mirrors env: `python -m bacnet_toolshed.discover … --address 192.168.x.x/24:47808`.

---

## REST quick reference

Full paths and auth: [Bridge API — BACnet](../appendix/bridge_api#bacnet).

Commission-only jobs: `GET /api/bacnet/jobs/{job_id}` after `discover` / `point-discovery` / `supervisory-check` (202 + job id).

---

## Related

- [BACnet toolshed](index) — CLI modules and workspace paths
- [bacnet_toolshed/README.md](https://github.com/bbartling/open-fdd/blob/master/bacnet_toolshed/README.md) — command examples
- [BRICK + BACnet modeling](../bacnet-rdf-and-brick)
- [Security hardening](../security_hardening) — write gates and auth
