# Open-FDD OS (future)

Thin Linux host image for edge BACnet buildings: read-only root, Docker engine, RAUC OTA.

## Layers (today vs planned)

| Layer | Repo | Today |
|-------|------|--------|
| Host OS | `os/` | Ubuntu 24.04 + Docker CE |
| Supervisor | `supervisor/` | Compose + manifest |
| Apps | `docker/` | bridge, commission, poll, mcp-rag |
| State | `workspace/` | Bind-mounted on host |
| Deploy | `infra/ansible/` | Image tar until OTA |

Application logic stays in **published container images**, not the OS image.

## Layout

```text
open-fdd/
  os/              ← Buildroot / board support (planned)
  supervisor/      ← Addon manifest + compose
  docker/          ← Image build
  workspace/       ← Feather, rules, model
  infra/ansible/   ← Field deploy
```

## Roadmap

[Documentation/roadmap.md](Documentation/roadmap.md)

## Development today

Use Ubuntu edge hosts (Acme VM, bensserver, Pi) with `./infra/ansible/deploy.sh docker`. Do **not** depend on `os/` for current deploys. Docs: [Getting started](../docs/getting_started.md).
