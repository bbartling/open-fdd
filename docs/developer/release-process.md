---
title: Release process
parent: Developer
nav_order: 8
---

# Release process

Open-FDD has **two publish paths**:

| Artifact | Trigger | Registry |
|----------|---------|----------|
| **PyPI** `open-fdd` | Git tag `vX.Y.Z` (or legacy `open-fdd-vX.Y.Z`) | [pypi.org/project/open-fdd](https://pypi.org/project/open-fdd/) |
| **Docker** edge stack | Same release tag (or manual workflow) | `ghcr.io/bbartling/openfdd-*` |

Do **not** publish from ordinary branch pushes. Merge to `master`, bump version, tag, push tag.

## 1. Prepare version

```bash
git checkout master
git pull --ff-only
# Edit pyproject.toml + open_fdd/__init__.py → same X.Y.Z
python scripts/release/check_version.py
```

## 2. Merge and tag

```bash
git tag -a v3.0.30 -m "open-fdd 3.0.30"
git push origin v3.0.30
```

Tag push runs:

- `.github/workflows/publish-open-fdd.yml` — build, test, `twine check`, PyPI via **Trusted Publishing**
- `.github/workflows/docker-publish.yml` — GHCR images with tags `3.0.30`, `3.0`, `latest`

Legacy tag `open-fdd-v3.0.30` is still accepted during transition.

## 3. PyPI Trusted Publishing setup (one-time)

On [pypi.org](https://pypi.org) → project **open-fdd** → Publishing → **Add a new trusted publisher**:

| Field | Value |
|-------|--------|
| PyPI project name | `open-fdd` |
| Owner | `bbartling` |
| Repository | `open-fdd` |
| Workflow name | `Publish open-fdd to PyPI` |
| Environment | `pypi` (optional; enables approval gate) |

No long-lived API token in the repo.

## 4. Verify release

```bash
pip install open-fdd==3.0.30
python -c "import open_fdd; print(open_fdd.__version__)"

docker pull ghcr.io/bbartling/openfdd-bridge:3.0.30
docker manifest inspect ghcr.io/bbartling/openfdd-bridge:3.0.30
```

## 5. Manual workflow_dispatch

- **PyPI:** `Publish open-fdd to PyPI` with `dry_run=true` (default) — build/test only
- **Docker:** `Publish Docker images to GHCR` — publishes `:latest` (maintainer use)

## Package vs Docker

See [PyPI package](pypi-package.md) and [Docker images](../ops/docker-images.md).
