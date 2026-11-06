# scripts/nf/tools: read-only NF checks

Command-line tools that look at a Normal Framework box from outside. They only **read**, they use the Python
standard library (the BACnet check also needs `bacpypes3`), and they are **tag-driven**: sites, equipment, points,
devices and BACnet bindings all come from NF's Haystack model. Nothing here names a building, point, uuid or IP.
To support a new site, tag it in NF ([Haystack tagging](../../../docs/operations/nf/haystack-tagging.md)).

| Tool | What |
|---|---|
| `nf_portal_sensors.py [lan\|portal] [--tags a,b]` | Print the site / device / equipment tree with live values over the LAN and/or the portal, then compare the two paths (same uuid and sample time must carry the same value) |
| `nf_sensor_history.py <markers> [--exclude m] [--days N] [--via lan\|portal] [--csv f]` | Pick one trended point by markers, pull its history, print a summary and a daily rollup |
| `nf_bacnet_validate.py --address <ip>/<prefix>` | Compare NF's BACnet server and every tagged field point with what the devices answer on the wire (needs `bacpypes3`; run on a PC, see [BACnet validation](../../../docs/operations/nf/bacnet-validate.md)) |
| `nf_common.py` | Shared settings, retrying HTTP, token, tag query helpers (imported by the three tools; not run directly) |

Run any of them with `--help`.

## Settings

Environment variables, optionally read from an env file you pass with `--env FILE` (or `NF_ENV_FILE`). Values
already in the environment win. Keep the file outside git (`*.env` is gitignored; use `~/.secrets/`).

```
NF_LAN_URL=https://<nf-host>                     # LAN path: NF console port or your TLS front door
NF_CA_FILE=/path/to/lan-ca.crt                   # optional: self-signed LAN certificate to trust
NFURL=https://<installation-uuid>.normal-online.net   # optional: the Normal Online portal path
NF_CLIENT_ID=change-me                           # an NF API key (console: Settings > API Keys), read-only is enough
NF_CLIENT_SECRET=change-me
```

```bash
python3 scripts/nf/tools/nf_portal_sensors.py --env ~/.secrets/nf_api.env --tags discharge,air,temp
python3 scripts/nf/tools/nf_sensor_history.py outside,air,temp --exclude weather --days 3 --env ~/.secrets/nf_api.env
python3 scripts/nf/tools/nf_bacnet_validate.py --address 192.0.2.50/24 --env ~/.secrets/nf_api.env
```

Exit code 0 means everything matched; 1 means a mismatch, an unreachable path or missing settings (2 means a missing
optional dependency).

## Notes

- Transient errors (403, 429, 5xx) are retried: NF's front occasionally answers the token call with an empty-body 403.
- Through the portal an API key cannot read `/api/v1/bacnet/*` (401); the BACnet server check needs the LAN path.
- These tools are separate from `hooks/nf_app_sync.py`, which deploys and needs the console login. API keys here are
  read-only.
- Never run `nf_bacnet_validate.py` or other BACnet stacks on the NF box or a Pi (UDP 47808 is NF's).
