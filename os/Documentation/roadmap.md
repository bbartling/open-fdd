# Open-FDD OS roadmap

**Future concept** — track progress here; do not block 3.2.x patch releases on these items.

Design principles:

- **Lightweight** — Buildroot or similar; no desktop distribution
- **Docker-first** — container engine is the only app runtime on the host
- **Rust apps in GHCR** — `open_fdd_edge_prototype` + `openfdd-mcp`; no host Python
- **OTA** — RAUC A/B slots (future); offline `docker load` / GHCR pull until then
- **Read-only root** — SquashFS rootfs; mutable state under `/var/openfdd/workspace`
- **Board support** — x86_64 UEFI (bench VM), Raspberry Pi 4/5 ARM64 (field)

## Phases

| Phase | Deliverable | Status (3.2.3-prep) | Notes |
| --- | --- | --- | --- |
| **A** | Ubuntu/Pi OS + Docker + compose recipes + lifecycle scripts | **Shipping** | [`openfdd_stack_up.sh`](../../scripts/openfdd_stack_up.sh); recipes in [`docker/`](../../docker/) |
| **B** | GHCR multi-arch stack + MCP images, version pins | **Shipping** | `ghcr.io/bbartling/openfdd-{central,ui,fieldbus,mqtt,mcp}`; tag via `VERSION` + CI |
| **C** | `os/buildroot-external` board defconfig (x86_64, then Pi) | **Not started** | Docker pre-installed, no apt on target; placeholder dir only |
| **D** | RAUC OTA for OS + supervisor bundle (compose + manifest) | **Not started** | Replace manual pull/recreate; rollback slot |

## Phase C sketch (when started)

```text
os/
  buildroot-external/
    board/openfdd/x86_64/     # UEFI, Docker CE, RAUC stub
    board/openfdd/rpi4/       # ARM64, same stack
  rauc/
    manifest.raucm            # A/B update descriptor (future)
```

Supervisor manifest (future) might pin:

```yaml
# conceptual — not implemented
image_tag: 3.3.0        # applies to all stack images
recipe: standalone      # standalone | central | edge | csv
workspace_mount: /var/openfdd/workspace
```

Today those pins are operator env (`OPENFDD_IMAGE_TAG`) and Compose profiles.

## Non-goals (OS program)

- Host `pip install` / legacy Python bridge
- Bundling MCP or Ollama inside the bridge image
- Multiple unrelated compose projects on one appliance
- Public-internet exposure of bridge or MCP

## See also

- [concept.md](concept.md) — Home Assistant OS inspiration
- [../README.md](../README.md) — folder index
- [../../docs/quick-start/rust-site-lifecycle.md](../../docs/quick-start/rust-site-lifecycle.md) — current update path
