# Open-FDD OS (future)

Thin Linux host image for edge BACnet buildings — modeled after [Home Assistant Operating System](https://github.com/home-assistant/operating-system).

## Target architecture (HA OS analogue)

| Home Assistant | Open-FDD (this repo) | Status |
|----------------|----------------------|--------|
| HA OS (Buildroot) | **`os/`** — read-only root, Docker engine, RAUC OTA | **Planned** |
| Home Assistant Supervisor | **`supervisor/`** — compose, addons manifest, health | **Today** (Ubuntu + Ansible) |
| Home Assistant Core + Add-ons | **`docker/`** images + **`workspace/`** state | **Today** |

The OS layer is intentionally **minimal**: boot, networking, Docker, and persistent `/var/openfdd`. All application logic lives in **published container images** managed by the supervisor.

## Repository layout

```
open-fdd/
  os/              ← Buildroot / board support (future)
  supervisor/      ← Addon manifest + compose contracts
  docker/          ← Image build (Dockerfile targets)
  workspace/       ← Bind-mounted state (feather, rules, model)
  infra/ansible/   ← Pushes supervisor + images to field hosts (until OTA)
```

## Roadmap

See [Documentation/roadmap.md](Documentation/roadmap.md).

## Development today

Use a normal Ubuntu 24.04 edge host (Acme VM, Pi) with Docker CE and `./infra/ansible/deploy.sh docker`. Do **not** depend on this directory for current deploys.
