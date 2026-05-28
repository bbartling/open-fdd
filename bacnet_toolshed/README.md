# BACnet toolshed (Open-FDD)

BACpypes3 tools for **commissioning** BACnet points and **polling** present-values into local CSV under `workspace/bacnet/`. No AWS IoT / MQTT — output is meant for the Open-FDD bridge, Feather ingest, and `open_fdd.engine` FDD.

## Install (Linux edge / dev host)

```bash
cd /path/to/open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -r bacnet_toolshed/requirements.txt
export OPENFDD_REPO_ROOT=$PWD
```

## OT NIC / BBMD (required on every command)

Pass **BACpypes3** device args after the module options:

```bash
python -m bacnet_toolshed.discover 0 4194303 \
  --site-id demo --building-id plant1 \
  --name OpenFddEdge --instance 599999 \
  --address 192.168.1.50/24:47808
```

MS/TP via IP router:

```bash
  --route-aware --network 1 --router-ip 192.168.1.1 --mstp-net 2000
```

## Workspace layout

| Path | Purpose |
|------|---------|
| `workspace/bacnet/commissioning/points_discovered.csv` | Full discover output |
| `workspace/bacnet/commissioning/devices_discovered.csv` | Devices-only discover |
| `workspace/bacnet/commissioning/points.csv` | Enabled points for polling |
| `workspace/bacnet/polls/samples.csv` | Long-format poll output |
| `workspace/bacnet/jobs/` | Commission agent job metadata |

## Typical workflow

```bash
# 1) Discover devices (fast)
python -m bacnet_toolshed.discover_devices 0 4194303 \
  --name OpenFddEdge --instance 599999 --address 192.168.1.50/24:47808

# 2) Discover points per device (or full discover in one shot)
python -m bacnet_toolshed.discover 0 4194303 -o workspace/bacnet/commissioning/points_discovered.csv \
  --name OpenFddEdge --instance 599999 --address 192.168.1.50/24:47808

# 3) Enable points for polling (edit brick_class in CSV or use --match)
python -m bacnet_toolshed.enable_points \
  --input workspace/bacnet/commissioning/points_discovered.csv \
  --output workspace/bacnet/commissioning/points.csv \
  --match temperature --poll-interval 60

# 4) Poll → local CSV (systemd-friendly)
python -m bacnet_toolshed.poll_driver \
  --config workspace/bacnet/commissioning/points.csv \
  --interval 60 --once \
  --name OpenFddEdge --instance 599999 --address 192.168.1.50/24:47808
```

## Commission HTTP agent (optional)

Lightweight job runner for discover (port **8767** by default, separate from bridge **8765**):

```bash
cp bacnet_toolshed/commission.env.example workspace/bacnet/commissioning/commission.env
# edit SITE_ID, BACNET_BIND, etc.
python -m bacnet_toolshed.commission_agent
curl -X POST http://127.0.0.1:8767/api/jobs/discover -H 'Content-Type: application/json' -d '{}'
```

## systemd (Linux edge)

See `bacnet_toolshed/systemd/` for unit templates. After `workspace/` API + dashboard exist, run poll on a timer and let the bridge ingest `polls/samples.csv`.

## Next: UI + data modeling

- **`skills/driver-bacnet-ingest`** — bridge routes `/config/bacnet`, `/ingest/bacnet`
- **`skills/react-operator-dashboard`** — `/bacnet-tools` page (to be generated under `workspace/dashboard`)
- AI agent fills **`brick_class`** / **`column_map`** on commissioning CSV, runs FDD via `open_fdd.engine`

## Modules

| Module | Role |
|--------|------|
| `discover` | Who-Is + object-list → points CSV |
| `discover_devices` | Who-Is → devices CSV only |
| `discover_points` | Points from devices CSV |
| `merge_points_csv` | Merge `device_*.csv` |
| `enable_points` | Set `enabled=1` on commissioning rows |
| `poll_driver` | RPM poll → `polls/samples.csv` |
| `commission_agent` | HTTP discover jobs |

**Not included:** `mqtt_payload`, AWS IoT `read_driver` (use `poll_driver` instead).
