---
name: openfdd-nf-provider
description: >-
  Use when adding or changing a Normal Framework (NF) portal provider site for
  Open-FDD central: OPENFDD_PROVIDER_SITES JSON, provider_sites.<site>.json,
  point_map roles, the hourly completed-hour portal pull, the 7-day NF history
  window, and backfill limits. Triggers on: NF provider, provider_sites,
  OPENFDD_PROVIDER_SITES, normal-online.net, point_map, NF_CLIENT_ID, hourly pull,
  portal history gap, bosspi, ACME NF, NF transport, rest or grpc, LAN gRPC.
---

# NF portal provider (Open-FDD central)

`architecture_epoch: portal-timescale-v1`.

Open-FDD does not talk BACnet. A site runs **Normal Framework** at the edge. NF
discovers and trends the BACnet points. Open-FDD central pulls that history over
HTTPS from the NF portal tunnel (`https://<installation-uuid>.normal-online.net`)
into Timescale. A site can instead read history from the NF LAN gRPC API
(`transport: "grpc"`, see below). Code: [`services/central/src/providers/`](../../../services/central/src/providers/)
(`config.rs`, `nf.rs`, `nf_transport.rs`, `hourly.rs`, `poller.rs`, `map.rs`).

Edge install, licensing, BACnet scan, and trend periods: [`openfdd-nf-edge-bench`](../openfdd-nf-edge-bench/SKILL.md).

## Add a site

1. NF at the site is licensed, the portal tunnel answers, and the points you need
   are trending (a poll `period` is set in NF). Untrended points have no history.
2. Create an NF API key on that box (see `openfdd-nf-edge-bench`). Store the id and
   secret only in an env file outside git (`chmod 600`). Config uses
   `env:NAME` references, never literals.
3. Write a site file outside git (for example `~/.config/openfdd/sites/<site>.json`;
   shape below). Point ids are NF point **UUIDs**. Never match NF display names
   (`map.rs` forbids substring / prefix / `LIKE` role inference). The repo ships
   only [`scripts/nf/provider_sites.example.json`](../../../scripts/nf/provider_sites.example.json).
4. Point central at it:
   - one file: `OPENFDD_PROVIDER_SITES=/path/to/site.json`
   - several files: comma-separated paths
   - a directory: every `*.json` in the directory (sorted)
   Inline JSON also works. Use distinct `env:NAME` refs per site when multiple
   portals share one central. Restart only the stack you own.
5. Smoke one UUID with [`scripts/nf/read_sensors.py`](../../../scripts/nf/read_sensors.py)
   (`NF_POINT_UUIDS`), then check provider health in central.

**NF MCP (read-only):** prefer the Normal Framework MCP connector for inventory
and trend checks (`search_points`, `read_values`, `diagnose`) — not BACnet
`control` or HVAC writes. Open-FDD central never needs NF write RPCs for ingest.

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
    "client_id": "env:NF_CLIENT_ID_SITE_A",
    "client_secret": "env:NF_CLIENT_SECRET_SITE_A",
    "poll_secs": 3600,
    "transport": "rest",
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
  role, normalized by `normalize_role`), optional `equip_type`, `units` (alias
  `unit`), `kind`, `semantic_point_id`, and `provisional: true` for a mapping
  not yet confirmed.
- `units` is the site-file fallback when NF omits the unit or reports it as
  unknown (JavaScript hook points often do). After inventory sync, run a **units
  audit**: list committed points with empty `unit` and declare them through
  `POST /api/model/point` with `confirm:true` (or MCP `openfdd_model_point_upsert`).
  See [`docs/modeling/provider-point-overlay.md`](../../../docs/modeling/provider-point-overlay.md).
  Ingest reads the NF unit first,
  converts temperature to the historian canonical unit (`degF`, imperial-f-v1)
  on the existing sample before the single Timescale write, and keeps the
  source unit on the point (`source_unit`). If NF and `units` name different
  units, the sample is withheld and logged as `nf_unit_mismatch`. A converted
  temperature outside the role range is withheld as `nf_unit_range`.
- `equip_type` is the classifier (rule 64). Do not encode type in `equipment_id`.
- Anonymous access is lab-only (`auth_mode: "anonymous"`) and only with no
  credential fields. `network_scope: "private"` is needed for RFC1918 endpoints.
- `transport` picks the NF history read for the site. It is validated config,
  not a guess:
  - `rest` (default when absent): portal HTTPS `GET /api/v1/point/data`. The
    Connection column shows **Portal (HTTPS)**.
  - `grpc`: NF LAN `PointManager.GetData` over TLS with certificate
    verification, per-request deadlines and message limits
    ([`crates/nf_grpc`](../../../crates/nf_grpc/)). The Connection column shows
    **LAN (gRPC)**. Requires `provider: "nf"`, an `https://` endpoint and
    `client_id` / `client_secret` (the bearer is minted the same way as REST).
    Anonymous or `allow_insecure_http` sites are rejected
    (`grpc_requires_credentials`, `grpc_tls_required`).
  - Any other value fails the site with `transport_invalid`. A non-NF provider
    with `grpc` fails with `transport_unsupported`.
  - There is **no automatic fallback**. A failed gRPC read is a recorded gRPC
    failure (`grpc_<status>` retry code on the ingest job), never a silent REST
    retry. To switch, change `transport` and restart the stack you own.
  - Both transports feed the same ingest queue, hourly planner and Timescale
    writer, and produce the same normalized samples. Inventory sync still
    uses the portal REST API.
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
- A central restart resets the provider poller. Health reads `awaiting_poll` until
  the next hourly pull. `scripts/nf/validate_live.py` may report an unclean pull
  when the hourly path recorded samples under `samples_handed_off` (a success
  still sets a health message such as `committed`). Trust the Timescale row counts
  for that hour.
- `poll_secs` is the loop cadence. Use `3600` for NF (one completed hour per tick).
  The NF trend period (e.g. 60 s or 300 s) is set in NF, not here.
- Env knobs: `OPENFDD_HOURLY_BOOTSTRAP_HOURS` (max 720), `OPENFDD_HOURLY_RETENTION_HOURS`
  (max 2160, but NF only has ~168 h), `OPENFDD_HOURLY_RECONCILE_HOURS`,
  `OPENFDD_HOURLY_POINTS_PER_SHARD`. `OPENFDD_HOURLY_WINDOW_SECS` is for fast
  validation only.
- To backfill a new site, raise bootstrap up to 168 h on first start. Anything
  older than 7 days needs a CSV package import instead.

## Example in the repo

| File | What |
| --- | --- |
| [`scripts/nf/provider_sites.example.json`](../../../scripts/nf/provider_sites.example.json) | Two-site template with placeholder hosts, UUIDs, and per-site `env:NF_CLIENT_*` names |

Real maps live on the operator host (`scripts/nf/.gitignore` blocks
`provider_sites.*.json` except the example).

## Verify a site (freshness check)

With the NF MCP connected (see `openfdd-nf-edge-bench`), use `read_values` `latest`
on the provider UUIDs and `diagnose` `overview` for a quick look. The script below is
the scripted, repeatable check that must PASS.


After onboarding, and whenever charts look stale, run the portal freshness check:

```bash
python3 scripts/nf/check_portal_fresh.py \
  --env ~/.secrets/nf_<site>.env \
  --sites ~/.config/openfdd/sites/<site>.json \
  --points ~/.config/openfdd/sites/<site>_probes.json
```

(`--sample EQUIP:ROLE` replaces `--points` for a short list.) It reads the remote
portal only, never prints secrets, and needs PASS: every probed point and every
`weather` point newer than 30 min (`--max-age-min`), numeric and plausible. Warn
when a hook point is older than one hook interval plus a margin (`--warn-age-min`,
default 25 for a 20 min hook). WARN does not change the exit code. NF
`DEGREES_CELSIUS` readings are converted to °F for the range check. Impossible
readings (for example dewpoint above dry bulb) fail the run.

## Weather and other NF hooks

Internet weather comes from an NF JavaScript hook. Open-FDD does not fetch it.
The code is kept in this repo: [`scripts/nf/hooks/`](../../../scripts/nf/hooks/README.md)
holds the hook source, its manifest, and `nf_app_sync.py` (push, run now, status,
diff, pull). **Declare the hook cadence in the manifest** (`mode: scheduled`, rrule
with `DTSTART` + interval) so portal freshness checks and OAT-METEO **as-of bounds**
use the same interval (for example 20 min hook → `web_cadence_seconds` near 1200
plus margin in Lab). Tag web weather points distinctly from local BAS OAT: map hook
variables with `equip_type: weather` and `web-outside-air-*` roles so they never
shadow the site's own `outside-air-temp` sensors.

## Do not

- Do not stand up `openfdd-fieldbus`, BACnet Who-Is, or an MQTT broker to fill a
  site. Those are `historical/non-executable` (see
  [`openfdd-bacnet-ot-debug`](../openfdd-bacnet-ot-debug/SKILL.md)).
- Do not commit NF client secrets, portal passwords, or license material.
- Do not call NF gRPC write or control RPCs. The gRPC transport is a history read.
- Do not edit hook JS only in the NF console. Pull it back into `scripts/nf/hooks/` and commit it.
- Empty charts with rows in Timescale are a role gap: [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md).
