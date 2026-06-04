# BACnet single-stack — reference

## Port map (Open-FDD local stack)

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| Bridge + dashboard | 8765 | TCP | HTTP API; does not bind BACnet |
| Commission agent HTTP | 8767 | TCP | Proxies to one BACpypes3 app |
| BACnet/IP | 47808 | UDP | **Exclusive** — one listener per host |
| Caddy (optional) | 80 / 443 | TCP | Front door only |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `BACNET_BIND` | In `commission.env`; NIC IP/prefix:port |
| `BACNET_NAME` | Local device name (default `OpenFDD`) |
| `BACNET_INSTANCE` | Local device instance (default `599999`) |
| `OFDD_BACNET_BIND` | Runtime override for bind resolution |
| `OFDD_BACNET_BIND_STRICT=1` | Disable auto-replace of 127.0.0.1 with LAN IP |
| `OPENFDD_BACNET_COMMISSION_URL` | Default `http://127.0.0.1:8767` |

## Scripts

| Script | Use |
|--------|-----|
| `./scripts/bacnet_whois_smoke.sh` | Who-Is smoke (bacpypes3#125 pattern) |
| `./scripts/run_local.sh restart` | Restart commission agent after env change |
| `python -m bacnet_toolshed.smoke_whois` | Same as smoke script |

## Typical conflict scenario

1. Operator runs `mini_weather_device.py` on 47808 for lab.
2. `./scripts/run_local.sh start` starts commission agent — second bind fails or first app keeps port.
3. Dashboard Who-Is returns empty or errors.

**Fix:** stop simulator → restart Open-FDD stack → smoke test → dashboard Who-Is.
