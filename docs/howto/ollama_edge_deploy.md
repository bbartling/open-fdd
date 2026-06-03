---
title: Ollama on the edge (hardware)
parent: How-to guides
nav_order: 8
---

# Ollama on the edge (hardware)

Open-FDD uses the official [`ollama/ollama`](https://hub.docker.com/r/ollama/ollama) image or a **host binary** from Ansible `ollama_bootstrap.yml`. Purpose: [Local Ollama (check-engine)](../local_ollama) — not deployment AI.

## Recommended by hardware

| Situation | Approach |
|-----------|----------|
| **x86/ARM VM with NVIDIA GPU** | Host systemd Ollama (`openfdd_docker_ollama: false`) + `deploy.sh ai` |
| **No GPU / small Pi** | Docker `ollama` service or disable AI |
| **GPU in Docker** | NVIDIA Container Toolkit + `ollama_gpu_mode: gpu` |

## Variables (`host_vars` / `group_vars`)

| Variable | Role |
|----------|------|
| `enable_ollama` | Turn on AI stack |
| `openfdd_docker_ollama` | Host vs compose Ollama |
| `ollama_gpu_mode` | `cpu` \| `auto` \| `gpu` |
| `ollama_ram_tier` | Default model tier |

## Acme example

```bash
./scripts/docker_build.sh --save
cd infra/ansible && source secrets/acme.env.local
./deploy.sh docker --limit acme_vm_bbartling
./deploy.sh ai --limit acme_vm_bbartling
```

## Maintenance

- `ollama pull <model>` on host or `docker compose exec ollama ollama pull …`
- Logs: `journalctl -u ollama -f` or `docker compose logs -f ollama`
