# Docker / GHCR (self-host)

**Streamlit Community Cloud does not use this Dockerfile.** Cloud deploys from `streamlit_app.py` + `requirements.txt` — see [STREAMLIT_CLOUD.md](STREAMLIT_CLOUD.md).

## Runtime model

| Fact | Detail |
| --- | --- |
| Process inside the container | **Streamlit** listening on **internal port 8501** |
| Browser URL | Host port you publish, e.g. `-p 8501:8501` → http://localhost:8501 or `-p 8502:8501` → http://localhost:8502 |
| Default image mode | `APP_MODE=cloud` + `VIBE19_DOCKER=1` → **zip-only** UI (no Folder path) |
| Data retention | Zip extract under OS temp (`vibe19_*`); Clear session / wipe — not kept in the image |

**Port conflicts:** if something else already owns `:8501`, map a free host port (`-p 8502:8501` → http://localhost:8502).

## Newbie tutorial: keep Streamlit running long-term

Foreground `docker run` (no `-d`) dies when you close the terminal. A **running** container also **never** picks up a newer GHCR image by itself.

**Easy button** (pull tip + recreate):

```bash
# from vibe_code_apps_19/
./scripts/docker_update_vibe19.sh          # Linux / macOS / Pi — uses :latest
# Windows: .\scripts\docker_update_vibe19.ps1
```

Or by hand — prefer **`:latest`** (same tip as `:develop` while default branch is `develop`):

1. **`docker pull ghcr.io/bbartling/vibe19:latest`**
2. **`docker stop` / `rm` / `run -d --restart unless-stopped …`**
3. Browse the published host port

| Tag / UI | Meaning |
| --- | --- |
| `:latest` / `:develop` | Moving tip of develop |
| `:sha-…` | Pin one commit (what GHCR often labels “Latest” on the package page — that badge ≠ auto-update) |

| Flag | Meaning |
| --- | --- |
| `docker pull` | Required every update — `docker run` alone reuses a stale local image |
| `-d` | Detached — process stays up after the shell closes |
| `--restart unless-stopped` | Restart on crash or host/Docker reboot until you `docker stop` |
| `-p HOST:8501` | Map a free host port to Streamlit inside the container |
| `--name vibe19` | Stable name for stop / start / logs |
| Do **not** pass `--rm` | `--rm` deletes the container on stop (fine for one-shot tests only) |

**Linux / macOS / Raspberry Pi (64-bit):**

```bash
docker pull ghcr.io/bbartling/vibe19:latest
docker stop vibe19 2>/dev/null; docker rm vibe19 2>/dev/null
docker run -d --restart unless-stopped -p 8502:8501 --name vibe19 \
  ghcr.io/bbartling/vibe19:latest
# open http://localhost:8502  (or http://<pi-ip>:8502)
```

**Windows PowerShell:**

```powershell
docker pull ghcr.io/bbartling/vibe19:latest
docker stop vibe19 2>$null; docker rm vibe19 2>$null
docker run -d --restart unless-stopped -p 8502:8501 --name vibe19 `
  ghcr.io/bbartling/vibe19:latest
# open http://localhost:8502
```

Day-to-day commands:

```bash
docker ps                 # running?
docker logs -f vibe19     # follow Streamlit logs (Ctrl+C leaves the app running)
docker stop vibe19        # stop (disables restart until you start again)
docker start vibe19       # start the same container (still the *old* image)
./scripts/docker_update_vibe19.sh   # actually get a newer build
```

**One-shot test** (foreground; Ctrl+C stops; container deleted):

```bash
docker run --rm -p 8502:8501 --name vibe19-test ghcr.io/bbartling/vibe19:latest
```

## Two-tier size limits

| Path | Limit | Mechanism |
| --- | --- | --- |
| Browser `st.file_uploader` | **500 MB** | `.streamlit/config.toml` → `server.maxUploadSize = 500` |
| Agent / CLI / path load | **2048 MB** default | `DEFAULT_PACKAGE_MB` (`OPENFDD_MAX_*` env override) |

## Build & run (local image)

```powershell
cd vibe_code_apps_19
docker build -t vibe19 .
docker run --rm -p 8501:8501 --name vibe19-test vibe19
```

## Pull from GHCR

Workflow: `.github/workflows/vibe19-ghcr.yml` → `ghcr.io/bbartling/vibe19` on pushes to `develop`/`main` that touch `vibe_code_apps_19/**`, tags `vibe19-v*`, or `workflow_dispatch`.

**Scope:** this workflow publishes **Vibe 19 only** (`ghcr.io/bbartling/vibe19`). Compressor-runtime / WattLab v3 work does **not** publish, retag, or update any Vibe 20 GHCR image — Vibe 20 remains a **local checkout / consumer** of the WattLab dump zip. Established Vibe 19 pull/run instructions below are unchanged. After merge to `develop`, expect moving tips `:develop` / `:latest` plus immutable `:sha-<git>` (multi-arch amd64+arm64). Always `docker pull` then recreate — running containers never auto-update.

**Architectures (multi-arch manifest):**

| Platform | Typical hardware |
| --- | --- |
| `linux/amd64` | x86_64 PCs / servers |
| `linux/arm64` | Raspberry Pi **4 / 5** (64-bit OS), Apple Silicon (native) |

`docker pull` / `docker run` pick the matching arch automatically. On a Pi 4/5 with 64-bit Raspberry Pi OS:

```bash
docker pull ghcr.io/bbartling/vibe19:develop
docker run --rm -p 8501:8501 --name vibe19 ghcr.io/bbartling/vibe19:develop
# open http://<pi-ip>:8501
```

To confirm the local image arch:

```bash
docker image inspect ghcr.io/bbartling/vibe19:develop --format '{{.Architecture}}'
# arm64 on Pi 4/5 64-bit
```

### Publishing good containers (agents)

**Non-negotiable for model/agent sessions** (see `vibe19_agent_spec/AGENTS.md` rule **30**):

1. Publish only through `.github/workflows/vibe19-ghcr.yml`.
2. That workflow **must** keep:
   - `docker/setup-qemu-action` with `platforms: amd64,arm64`
   - Buildx publish platforms `linux/amd64,linux/arm64` (env `PUBLISH_PLATFORMS`)
   - Post-push **Verify multi-arch manifest** step that greps both platforms
3. Never push a tip image as amd64-only “just to unblock” a Pi pull — rebuild multi-arch.
4. If pulls fail with `manifest … not found` / missing blob digests (tags point at deleted/incomplete layers):

```bash
gh workflow run vibe19-ghcr.yml --ref develop -f no_cache=true
# wait for success, then:
docker pull ghcr.io/bbartling/vibe19:latest
docker buildx imagetools inspect ghcr.io/bbartling/vibe19:latest
# must list Platform: linux/amd64 and Platform: linux/arm64
```

5. Do **not** prune GHCR versions that shared layers with current tags; prefer no-cache rebuild.
6. After any workflow edit that touches platforms/QEMU/cache, confirm Actions is green and the inspect command above still shows both arches.

```powershell
docker pull ghcr.io/bbartling/vibe19:develop
# :latest when the default-branch job publishes it
# Always pass the *tagged* name so `docker ps` IMAGE is readable (not caab217c7f84):
docker run --rm -p 8501:8501 --name vibe19 ghcr.io/bbartling/vibe19:develop
```

Pinned build (immutable):

```powershell
docker pull ghcr.io/bbartling/vibe19:sha-<full-or-short-git-sha>
docker run --rm -p 8502:8501 --name vibe19-pin ghcr.io/bbartling/vibe19:sha-<git-sha>
```

Optional short local alias:

```powershell
docker tag ghcr.io/bbartling/vibe19:develop vibe19:develop
docker run --rm -p 8501:8501 --name vibe19 vibe19:develop
```

If pull fails with 403: GitHub → Packages → `vibe19` → Package settings → visibility **Public** (or `docker login ghcr.io` with a PAT that has `read:packages`).

## Agent bootstrap + Docker (critical)

`scripts/agent_afdd.py` writes **host-native paths** into `streamlit_bootstrap.json` / `.last_agent_session.json` (e.g. `C:\Users\…\BUILDING_100.zip`). A **container cannot resolve Windows host paths**.

For GHCR / Docker:

1. Put the package zip + a bootstrap JSON on a host folder you will bind-mount.
2. Rewrite `package_path` (and any `fault_settings_path` / `column_map_path`) to **container-visible** paths such as `/data/package.zip`.
3. Pass `VIBE19_BOOTSTRAP=/data/….json` and mount that folder.

### Windows PowerShell example

```powershell
# Host folder with the zip + bootstrap (edit paths)
$dir = "C:\Users\ben\data\vibe19_docker"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item "C:\path\to\BUILDING_100_full_openfdd_package_v1.zip" "$dir\package.zip"

@'
{
  "schema_version": "openfdd_bootstrap_v1",
  "package_path": "/data/package.zip",
  "auto_run_rules": true,
  "notes": "Container-visible paths only — not Windows drive letters"
}
'@ | Set-Content -Encoding utf8 "$dir\VIBE19_BUILDING_100_BOOTSTRAP.json"

# If 8501 is busy, use 8502:8501 and browse localhost:8502
docker pull ghcr.io/bbartling/vibe19:develop
docker run --rm -p 8502:8501 `
  -v "${dir}:/data:ro" `
  -e VIBE19_BOOTSTRAP=/data/VIBE19_BUILDING_100_BOOTSTRAP.json `
  --name vibe19-b100 `
  ghcr.io/bbartling/vibe19:develop
```

Open **http://localhost:8502**. Expect package load + optional auto-run of all 50 rules per equipment. Sidebar may show **data-contract warnings** (quality window / columns.csv extras / topology gaps) — those are intentional, not crashes.

Skip slow auto-run while debugging UI:

```powershell
docker run --rm -p 8502:8501 -v "${dir}:/data:ro" `
  -e VIBE19_BOOTSTRAP=/data/VIBE19_BUILDING_100_BOOTSTRAP.json `
  -e VIBE19_BOOTSTRAP_SKIP_RULES=1 `
  ghcr.io/bbartling/vibe19:develop
```

### Headless agent on the host, Streamlit in Docker

Run `agent_afdd.py` on Windows to produce `fault_settings.json` / `session_config.json`, copy those into `/data`, and reference them from bootstrap with `/data/...` paths. Do **not** leave `C:\...` paths in the JSON the container reads.

## Folder mode (optional, local APP_MODE only)

```powershell
docker run --rm -p 8501:8501 -e APP_MODE=local `
  -v ${PWD}/data:/app/data `
  -e HVAC_DATA_ROOT=/app/data/hvac_systems_CLEANED `
  vibe19
```

## Branch protection vs GHCR Actions

Independent. Keep **`develop` loose** for iterate-fast; optional light protect on `main` later. Actions do not require branch protection.

## WattLab dump (Export → vibe20)

The GHCR `vibe19` image ships the **Export** WattLab dump (FDD findings, analytic CSVs, diurnal profiles, data-derived `model_seed.json`). EnergyPlus calibration/ECM screening lives in vibe20 (`ghcr.io/bbartling/vibe20` or a local checkout). Details: [vibe_code_apps_20/README.md](../vibe_code_apps_20/README.md).

## Notes

- Image includes `.streamlit/config.toml` (`maxUploadSize = 500`).
- Optional tighter caps: `-e OPENFDD_MAX_ZIP_MB=250 -e OPENFDD_MAX_UNCOMPRESSED_MB=250`
