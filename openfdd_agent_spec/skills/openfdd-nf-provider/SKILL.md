---
name: openfdd-nf-provider
description: >-
  Use when adding or changing a Normal Framework (NF) portal provider site for
  Open-FDD central: OPENFDD_PROVIDER_SITES JSON, provider_sites.<site>.json,
  point_map roles, the hourly completed-hour portal pull, the 7-day NF history
  window, and backfill limits. Triggers on: NF provider, provider_sites,
  OPENFDD_PROVIDER_SITES, normal-online.net, point_map, NF_CLIENT_ID, hourly pull,
  portal history gap, bosspi, ACME NF.
---

# NF portal provider (Open-FDD central)

`architecture_epoch: portal-timescale-v1`.

Open-FDD does not talk BACnet. A site runs **Normal Framework** at the edge. NF
discovers and trends the BACnet points. Open-FDD central pulls that history over
HTTPS from the NF portal tunnel (`https://<installation-uuid>.normal-online.net`)
into Timescale. Code: [`services/central/src/providers/`](../../../services/central/src/providers/)
(`config.rs`, `nf.rs`, `hourly.rs`, `poller.rs`, `map.rs`).

Edge install, licensing, BACnet scan, and trend periods: [`openfdd-nf-edge-bench`](../openfdd-nf-edge-bench/SKILL.md).

## Add a site

1. NF at the site is licensed, the portal tunnel answers, and the points you need
   are trending (a poll `period` is set in NF). Untrended points have no history.
2. Create an NF API key on that box (see `openfdd-nf-edge-bench`). Store the id and
   secret only in an env file outside git (`chmod 600`). Config uses
   `env:NAME` references, never literals.
3. Write `scripts/nf/provider_sites.<site>.json` (shape below). Point ids are NF
   point **UUIDs**. Never match NF display names (`map.rs` forbids substring /
   prefix / `LIKE` role inference).
4. Point central at it: `OPENFDD_PROVIDER_SITES=/path/to/provider_sites.<site>.json`
   (inline JSON also works). Restart only the stack you own.
5. Smoke one UUID with [`scripts/nf/read_sensors.py`](../../../scripts/nf/read_sensors.py)
   (`NF_POINT_UUIDS`), then check provider health in central.

Do not add a provider to a shared stack someone else is testing.

## provider_sites JSON

A list of site objects. Fields from `SiteConfigRaw` in `config.rs`:

```json
[
  {
    "building_id": "SITE_A",
    "tenant_id": "lab",
    "provider_instance_id": "nf-site-a",
    "provider": "nf",
    "endpoint": "https://<installation-uuid>.normal-online.net",
    "client_id": "env:NF_CLIENT_ID",
    "client_secret": "env:NF_CLIENT_SECRET",
    "poll_secs": 3600,
    "point_map": [
      {
        "provider_point_id": "<nf point uuid>",
        "equipment_id": "VAV_8",
        "role": "zone-air-temp",
        "equip_type": "vav"
      }
    ]
  }
]
```

- `point_map` entry: `provider_point_id`, `equipment_id`, `role` (Haystack SQL
  role, normalized by `normalize_role`), optional `equip_type`, `unit`, `kind`,
  `semantic_point_id`, and `provisional: true` for a mapping not yet confirmed.
- `equip_type` is the classifier (rule 64). Do not encode type in `equipment_id`.
- Anonymous access is lab-only (`auth_mode: "anonymous"`) and only with no
  credential fields. `network_scope: "private"` is needed for RFC1918 endpoints.
- `binding_set_path` / `binding_set_inline` can replace `point_map` with an
  inventory-approved Haystack binding set.

## Hourly pull and the 7-day window

- NF sites enqueue **completed-hour** jobs. Each job copies every raw sample in
  the last finished hour plus a short overlap. It does not downsample.
- Defaults (`HourlyPolicy` in `hourly.rs`): publication delay 300 s, overlap 300 s,
  first-run bootstrap 24 h, reconcile 2 recent hours, retention edge **7 days**.
- NF portal history is kept about **7 days**. Hours older than the retention edge
  are explicit, unrecoverable gaps. A central outage longer than 7 days loses data;
  there is no update-log cursor (`/api/v1/point/updates/data` returned 403).
- `poll_secs` is the loop cadence. Use `3600` for NF (one completed hour per tick).
  The NF trend period (e.g. 60 s or 300 s) is set in NF, not here.
- Env knobs: `OPENFDD_HOURLY_BOOTSTRAP_HOURS` (max 720), `OPENFDD_HOURLY_RETENTION_HOURS`
  (max 2160, but NF only has ~168 h), `OPENFDD_HOURLY_RECONCILE_HOURS`,
  `OPENFDD_HOURLY_POINTS_PER_SHARD`. `OPENFDD_HOURLY_WINDOW_SECS` is for fast
  validation only.
- To backfill a new site, raise bootstrap up to 168 h on first start. Anything
  older than 7 days needs a CSV package import instead.

## Examples in the repo

| File | What |
| --- | --- |
| [`scripts/nf/provider_sites.bosspi.json`](../../../scripts/nf/provider_sites.bosspi.json) | Bench Pi with one FEC, AHU-style roles, `poll_secs: 3600` |
| [`scripts/nf/provider_sites.bosspi.example.json`](../../../scripts/nf/provider_sites.bosspi.example.json) | Placeholder UUID template |
| [`scripts/nf/provider_sites.acme.json`](../../../scripts/nf/provider_sites.acme.json) | ACME: 230 points on 33 equipment (VAVs, RTU, hot-water plant, Tracer SC OA). The bare-minimum set the retired edge poll used, trended in NF at 300 s |

## Do not

- Do not stand up `openfdd-fieldbus`, BACnet Who-Is, or an MQTT broker to fill a
  site. Those are `historical/non-executable` (see
  [`openfdd-bacnet-ot-debug`](../openfdd-bacnet-ot-debug/SKILL.md)).
- Do not commit NF client secrets, portal passwords, or license material.
- Empty charts with rows in Timescale are a role gap: [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md).
