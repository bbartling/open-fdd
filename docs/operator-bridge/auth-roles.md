---
title: Auth and roles
parent: Operator Bridge
nav_order: 2
---

# Auth and roles

## Production (LAN / edge)

- Set `OFDD_AUTH_SECRET` and role passwords in `workspace/auth.env.local`.
- Bridge on non-loopback addresses **requires** auth unless explicit insecure dev flags are set (lab only).

| Role | Typical access |
|------|----------------|
| `viewer` | Read trends, faults, model tree |
| `operator` | Run batch FDD, acknowledge views |
| `integrator` | Rule Lab, bindings, model import |
| `commission` | BACnet writes (plus write guard) |
| `agent` | Agent tools / app-edit gates |
| `admin` | Full configuration |

Login: `POST /api/auth/login` → Bearer JWT on API calls.

## Localhost dev

`OFDD_BRIDGE_HOST=127.0.0.1` with `OFDD_AUTH_DISABLED=1` is acceptable on a single machine. **Never** use auth-disabled mode on a building LAN.

Full hardening: [Security]({{ "/security/" | relative_url }}).
