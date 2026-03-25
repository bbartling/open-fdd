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

4. **Same secret name for both packages will not work** — each PyPI project needs its **own** API token (or one user token with scope for **both** projects, pasted into **both** secrets if you accept that coupling). **`PYPI_OPENFDD_TOKEN`** must authorize uploads to **`open-fdd`**; **`PYPI_OPENFDD_ENGINE_TOKEN`** must authorize uploads to **`openfdd-engine`**.

### If CI shows `HTTPError: 403 Forbidden` on `twine upload`

That is **not** caused by the Python version used in Actions (3.12 vs 3.14). Typical causes:

- **Secret missing or wrong name** — In the job log, `TWINE_PASSWORD:` appears blank when the secret is unset or the workflow can’t read it. Confirm **Settings → Secrets and variables → Actions** on **`bbartling/open-fdd`** (not only a fork) and that the secret names match the workflow exactly.
- **Token scope** — PyPI “API token” must be tied to the **correct project** (`open-fdd` vs `openfdd-engine`) or be an account token with upload rights to that project.
- **You are not a maintainer** of the PyPI project — 403 until [ownership](https://pypi.org/help/#project-name) is fixed.
- **Re-upload** — PyPI rejects replacing the same version; bump **`pyproject.toml`** version and use a **new tag** if `0.1.1` already partially uploaded (rare for failed uploads).

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
