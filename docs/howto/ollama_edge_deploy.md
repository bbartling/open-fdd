---
title: Ollama on the edge (GPU / CPU / ARM / x86)
nav_exclude: true
---

# Ollama on the edge

Open-FDD does **not** build a custom Ollama image. Use the official [`ollama/ollama`](https://hub.docker.com/r/ollama/ollama) multi-arch image or the **host binary** from `ollama_bootstrap.yml`.

## Recommended by hardware

| Situation | Approach | Why |
|-----------|----------|-----|
| **x86/ARM VM with NVIDIA GPU** | **Host systemd Ollama** (`openfdd_docker_ollama: false`) + `./deploy.sh ai` | Simplest GPU access (no NVIDIA Container Toolkit required). Bridge uses `host.docker.internal:11434`. |
| **No GPU / small Pi** | Docker `ollama` service (`openfdd_docker_ollama: true`) or disable AI | Official image is multi-arch (`amd64`, `arm64`). Set `ollama_ram_tier` + model map in group_vars. |
| **GPU + insist on Docker** | `openfdd_docker_ollama: true`, `ollama_gpu_mode: gpu` | Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) on the host; compose template reserves GPU devices. |

## Variables (`host_vars` / `group_vars`)

| Variable | Typical value | Role |
|----------|---------------|------|
| `enable_ollama` | `true` on Acme | Turn on AI stack |
| `openfdd_docker_ollama` | `false` (Acme GPU path) / `true` (compose Ollama) | Where Ollama runs |
| `ollama_gpu_mode` | `cpu` \| `auto` \| `gpu` | Passed to `workspace/ollama.env.local` as `OFDD_OLLAMA_GPU_MODE` |
| `ollama_ram_tier` | `8gb` … `64gb` | Default model tier |
| `ollama_model_for_tier` | map in `pi_bcn.yml` | Pin models per tier |

## Acme (Docker apps + host Ollama)

```bash
./scripts/docker_build.sh --save
cd infra/ansible && source secrets/acme.env.local
./deploy.sh docker --limit acme_vm_bbartling
./deploy.sh ai --limit acme_vm_bbartling   # installs host Ollama + ollama.env.local
```

`ai` runs `ollama_bootstrap.yml` (arch-aware `amd64`/`arm64` tarball) — **not** a git rsync of app code.

## Maintenance

- **Models:** `ollama pull <model>` on the host or `docker compose exec ollama ollama pull …`
- **Upgrade Ollama:** bump `ollama_version` in `group_vars/pi_bcn.yml` and re-run `deploy.sh ai`, or `docker pull ollama/ollama:<tag>`
- **Logs:** `journalctl -u ollama -f` (host) or `docker compose logs -f ollama`

## Docker apps vs Ollama

Application containers (bridge, poll, commission, MCP) are **Open-FDD images**. Ollama stays **upstream** — same pattern as Home Assistant using official add-on/base images.
