---
title: PyPI releases (open-fdd + openfdd-engine)
parent: How-to Guides
nav_order: 20
---

# PyPI releases (`open-fdd` + `openfdd-engine`)

Two distributions are relevant for **contractors / pandas + YAML** workflows:

| PyPI project | What it is | When to publish |
|--------------|------------|-----------------|
| **`open-fdd`** | Main Python package: **`open_fdd.engine`** (`RuleRunner`, same YAML as the platform), optional extras (`[dev]`, `[platform]`, …). | When engine APIs, rule types, or packaging change. |
| **`openfdd-engine`** | Thin re-export of `RuleRunner`, `load_rule`, … — depends on **`open-fdd`**. | When you want a semver bump for integrators who pin `openfdd-engine` only. |

**Publish order:** release **`open-fdd`** first, then bump **`openfdd-engine`**’s `open-fdd>=…` constraint if needed and release **`openfdd-engine`**.

---

## 1) Before any release

1. **Choose versions**
   - Root **`pyproject.toml`** → `[project] version` for **`open-fdd`** (e.g. `2.0.8`).
   - **`packages/openfdd-engine/pyproject.toml`** → `version` and `dependencies` → `open-fdd>=X.Y.Z` aligned with what you just published (or still satisfied by `>=`).
2. **Changelog / tag message** — note engine-only docs, IoT `RuleRunner` usage, etc., if applicable.
3. **PyPI tokens** (GitHub → repo → **Settings → Secrets**):
   - **`PYPI_OPENFDD_TOKEN`** — API token for the **`open-fdd`** project on PyPI.
   - **`PYPI_OPENFDD_ENGINE_TOKEN`** — API token for the **`openfdd-engine`** project on PyPI.  
   (Use [trusted publishing](https://docs.pypi.org/trusted-publishers/) later if you prefer OIDC over long-lived tokens.)

---

## 2) Publish `open-fdd` (main package)

### Local dry run

```bash
cd /path/to/open-fdd   # repo root
python -m pip install --upgrade pip build twine
python -m build
twine check dist/*
# twine upload dist/*   # requires PYPI credentials
```

### GitHub Actions

- Workflow: **`.github/workflows/publish-open-fdd.yml`**
- **Upload runs only on a tag** matching **`open-fdd-v*`** (e.g. `open-fdd-v2.0.8`).
- **`workflow_dispatch`** runs **build + `twine check`** only (no upload) — use it to verify CI before tagging.

Example:

```bash
git checkout develop   # or your release branch
# bump version in pyproject.toml, commit
git tag open-fdd-v2.0.8
git push origin open-fdd-v2.0.8
```

---

## 3) Publish `openfdd-engine`

- Package path: **`packages/openfdd-engine`**
- Workflow: **`.github/workflows/publish-openfdd-engine.yml`**
- Tag pattern: **`openfdd-engine-v*`** (e.g. `openfdd-engine-v0.1.1`)
- Secret: **`PYPI_OPENFDD_ENGINE_TOKEN`**

Local build:

```bash
cd packages/openfdd-engine
python -m pip install --upgrade pip build twine
python -m build
twine check dist/*
```

---

## Scope policy

- **PyPI** is for the **installable Python packages** (engine + optional extras), not Docker images.
- **Full edge stack** (BACnet, Compose, bootstrap) stays **repo + Docker** as today.

See also: [Engine-only deployment and external IoT pipelines](engine_only_iot).
