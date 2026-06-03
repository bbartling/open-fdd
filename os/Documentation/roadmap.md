# Open-FDD OS roadmap

Design principles:

- **Lightweight** — no desktop distribution; Buildroot LTS kernel only
- **Docker-first** — container engine is the only app runtime
- **OTA** — RAUC A/B slots (future), offline bundles until then
- **Read-only root** — SquashFS rootfs; state on writable `/var/openfdd`
- **Board support** — x86_64 UEFI (Acme VM), Raspberry Pi 4/5 (field Pi)

## Phases

| Phase | Deliverable | Notes |
|-------|-------------|-------|
| **A (now)** | Ubuntu + Docker + `supervisor/manifest.yaml` + Ansible | Same operational model, faster iteration |
| **B** | GHCR-published images + version pins in manifest | `scripts/docker_publish.sh` |
| **C** | `os/buildroot-external` board defconfig for x86_64 | Docker pre-installed, no apt |
| **D** | RAUC OTA channel for OS + supervisor bundle | Replace tar `docker load` |

## Non-goals (for OS)

- Running `pip install` on the host for app code
- Multiple unrelated stacks on one edge (single `openfdd-edge` compose project)
