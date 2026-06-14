# Niagara baskStream connector (read-only)

Open-FDD integrates with **Niagara Framework** stations through the vendor **baskStream** module. The bridge API performs SCRAM login, opens a persistent WebSocket, and reads point values via MessagePack — the browser never connects directly to Niagara.

## Read-only posture

This connector is **read-only**. It does not implement writes, overrides, alarm acknowledge, or emergency actions. Use Niagara Workbench for OT commands.

## Niagara station setup

1. Install the **baskStream** module on the Niagara station (same module validated by `niagara-baskstream-python-tools` on Linux).
2. Add **BASkStreamService** (or equivalent baskStream service) on the station.
3. Ensure HTTPS (port **443**) is reachable from the Open-FDD bridge host.
4. Firewall: allow the bridge server → station on 443.

### Health check behavior

- **Before login:** `GET /stream/health` returns **302** redirect to `/login`.
- **After SCRAM login:** `GET /stream/health` returns **200** with JSON including `authenticatedUser`.

From Linux bench:

```bash
curl -k -i https://192.168.204.11/stream/health
# Expect 302 before login
```

## Open-FDD configuration

1. Copy `workspace/niagara.env.example` → `workspace/niagara.env.local` (gitignored).
2. Set `OPENFDD_NIAGARA_ADMIN_PASSWORD` (or your custom env name).
3. In the dashboard **Niagara** tab, add a station:
   - URL: `https://<station-ip>`
   - Username: Niagara web user
   - **password_env:** `OPENFDD_NIAGARA_ADMIN_PASSWORD`
   - **verify_tls:** off for self-signed bench certs
   - **default_points_root:** e.g. `slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points`

### ORD encoding

Niagara ORDs use encoded characters (`$20` = space, `$2d` = hyphen, `$23` = `#`). **Preserve these strings exactly** in config, API, and UI. Do not URL-decode or shell-expand them.

PowerShell users: use **single-quoted** strings for ORDs so `$20` is not treated as a variable.

### Allowed Origins

The Open-FDD **backend** connector does not require Niagara “Allowed Origins” for browser CORS — traffic is **Browser → Open-FDD `/api/niagara` → Niagara**. Direct browser-to-Niagara WebSocket is discouraged.

## Dependencies

Bridge API requires `aiohttp` and `msgpack` (see `workspace/api/requirements.txt`). If missing, the app still boots; `/api/niagara/health` reports `dependencies_ok: false`.

## Polling

Enable poll per station in the UI. The worker uses one persistent WebSocket per active station, batched reads, cached discovery metadata, and historian ingest with `source=niagara_baskstream`.

Disable background worker: `OFDD_DISABLE_NIAGARA_POLL_WORKER=1`.

## Bench reference (benserver)

| Item | Value |
|------|-------|
| Station URL | `https://192.168.204.11` |
| BACnet device folder | `slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points` |
| Expected points | ~10 BACnet components (proxy extensions excluded by default) |

Validate: **Test connection** → **Discover** → **Read selected** / **Poll once**. Values should match the standalone `baskstream_cli.py values` output (OA-T, DUCT-T, STAT ZN-T, etc.).
