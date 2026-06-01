# Open-FDD Supervisor

Orchestrates **Docker addons** on an edge host — the [Home Assistant Supervisor](https://github.com/home-assistant/supervisor) analogue.

## Responsibilities

| Supervisor | Does |
|------------|------|
| Addon manifest | Declares which images exist, ports, host-network exceptions |
| Compose contract | `docker/compose.dev.yml` (dev), Ansible-rendered `docker-compose.yml` (edge) |
| Health | Post-deploy checks in `infra/ansible/tasks/post_deploy_check.yml` |
| State paths | `workspace/` bind-mount; host Caddy on `:80` → bridge |

## Files

| File | Purpose |
|------|---------|
| [manifest.yaml](manifest.yaml) | Canonical addon list (names, build targets, profiles) |
| [compose/openfdd-edge.reference.yml](compose/openfdd-edge.reference.yml) | Human-readable edge stack (Ansible template is authoritative on hosts) |

## Deploy channels

| Channel | Command |
|---------|---------|
| **Dev (bensserver)** | `./scripts/openfdd_stack.sh up` |
| **Edge (Ansible)** | `./scripts/docker_build.sh --save` then `infra/ansible/deploy.sh docker` |
| **Future OTA** | Supervisor pulls pinned images from registry (see `docker/images.yaml`) |

## Adding an addon

1. Add a `build_target` in `docker/Dockerfile`
2. Register in `supervisor/manifest.yaml` and `docker/images.yaml`
3. Extend `docker/compose.dev.yml` and `infra/ansible/templates/docker-compose.edge.yml.j2`
4. Run `./scripts/docker_build.sh` and tests
