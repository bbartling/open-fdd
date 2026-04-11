---
title: Trivy security scanning
parent: How-to Guides
nav_order: 50
nav_exclude: true
---

# Trivy security scanning

**Trivy** is a CLI tool that scans container images, filesystems, config (Dockerfile, Compose), and secrets for vulnerabilities and misconfigurations. No server; run it locally or in CI. This guide covers when and how to use Trivy as part of Open-FDD development and security review.

See also: [Security and Caddy](../security) and [Operations testing plan](../operations/testing_plan) for broader hardening and validation context.

---

## Install Trivy

- **Linux (binary):** See [Trivy – Installation](https://aquasecurity.github.io/trivy/latest/docs/installation/). Typical: download the latest release for your arch and put the binary in `PATH`.
- **Docker:** `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image <image>`
- **CI:** Add a step that installs Trivy (e.g. from GitHub releases or a package manager) then runs the commands below.

---

## When to run Trivy

| When | What to run | Why |
|------|----------------|------|
| **After building stack images** | `trivy image <image>` for each built image | Find CVEs in OS packages and app dependencies before push or deploy. |
| **In CI / before merge** | Same image scan; optionally `trivy fs .` and `trivy config .` | Block PRs that introduce known vulnerabilities or bad config. |
| **After changing a Dockerfile or base image** | Build the image, then `trivy image <image>` | See impact of a base upgrade or new layers. |
| **After adding Python/Node dependencies** | `trivy fs .` (or scan the built image) | Check lockfiles and installed packages for known issues. |
| **Before release** | Full scan of all images + optional `trivy config stack/` | Final check for images and IaC. |

---

## Scan container images

Upstream **slim** compose builds **db** (+ optional Grafana/Mosquitto). If **you** maintain a **fork** that restores API, BACnet scraper, weather scraper, FDD loop, etc., scan those image names too. Image names depend on your Compose project (often `stack` if you run from `stack/` or with `-f stack/docker-compose.yml`).

1. **List built images:**
   ```bash
   cd stack && docker compose images
   ```
   Or after a full build: `docker images` and look for images built from the open-fdd stack (e.g. `stack-api`, `stack-bacnet-scraper`, `diy-bacnet-server:latest`).

2. **Scan each built image:**
   ```bash
   trivy image stack-api
   trivy image stack-bacnet-scraper
   trivy image stack-weather-scraper
   trivy image stack-fdd-loop
   trivy image stack-hoststats
   trivy image diy-bacnet-server:latest
   ```
   Replace with your actual image names if different (e.g. `openfdd-api` if your project name is `openfdd`).

3. **Options useful in dev:**
   - `trivy image --severity HIGH,CRITICAL <image>` — only high/critical findings.
   - `trivy image --exit-code 1 <image>` — exit non-zero if there are vulnerabilities (for CI).
   - `trivy image --ignorefile .trivyignore <image>` — ignore accepted risks (document in the file).

**Workflow:** Build → run Trivy → fix (update base image, bump packages) or add to `.trivyignore` with a comment → re-scan until you’re satisfied.

---

## Scan filesystem and config (optional)

- **Dependencies (lockfiles, etc.):**
  ```bash
  trivy fs .
  ```
  Scans the repo for known vulnerabilities in dependencies (e.g. `package-lock.json`, `requirements.txt`). Run from repo root.

- **Dockerfile / Compose misconfigs:**
  ```bash
  trivy config stack/
  ```
  Checks Dockerfile and Compose files for common misconfigurations.

- **Secrets:**
  ```bash
  trivy secret .
  ```
  Detects accidentally committed secrets. Use when adding or changing env or config.

---

## Script or Make target (optional)

To make “run Trivy” a single step for the team:

- **Script:** e.g. `scripts/trivy-scan.sh` that runs `docker compose -f stack/docker-compose.yml build` (or assumes images are already built), then `trivy image` for each built image, with `--exit-code 1` for CI.
- **Make:** In a top-level `Makefile`, add a target such as `trivy: build then trivy image for each stack image`.

Example (adapt image list to your project):

```bash
#!/usr/bin/env bash
# scripts/trivy-scan.sh - scan all built stack images
set -e
for img in stack-api stack-bacnet-scraper stack-weather-scraper stack-fdd-loop stack-hoststats; do
  if docker image inspect "$img" &>/dev/null; then
    echo "=== $img ==="
    trivy image --exit-code 1 --severity HIGH,CRITICAL "$img" || true
  fi
done
```

---

## Keeping docs up to date

Keep this howto and related docs in sync with the stack:

- When you add or rename a service or image in `stack/docker-compose.yml`, update the image list in this doc and in any `trivy-scan` script.
- When you change security practices (e.g. add CI Trivy, or a `.trivyignore` policy), update [Security](../security) and [Operations testing plan](../operations/testing_plan) if relevant.
- If you add a Trivy step to CI, document it in [Contributing](../contributing) or the CI workflow doc so contributors know scans run on every PR.
