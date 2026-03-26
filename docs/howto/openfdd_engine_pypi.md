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

### PyPI upload auth (required once per project)

CI uses **[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)** (OpenID Connect from GitHub). **No `TWINE_PASSWORD` / repo secrets** are required if this is configured.

For **each** PyPI project (`open-fdd` and `openfdd-engine`):

1. Log in to [pypi.org](https://pypi.org), open the project → **Manage project** → **Publishing**.
2. Under **Manage publishers**, add a **GitHub** publisher:
   - **Owner:** `bbartling` (your GitHub org or user)
   - **Repository name:** `open-fdd`
   - **Workflow name:** must match the file name exactly:
     - for **`open-fdd`** uploads → **`publish-open-fdd.yml`**
     - for **`openfdd-engine`** uploads → **`publish-openfdd-engine.yml`**
3. Save. PyPI may show a **pending** publisher until the first successful run.

Workflows use **`pypa/gh-action-pypi-publish@release/v1`** with **`permissions: id-token: write`**. Official guide: [Publishing package distribution releases using GitHub Actions CI/CD workflows](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

**After changing workflows:** Git tag builds use the workflow YAML from the **tagged commit**. Merge the updated workflows to **`master`**, then either **delete and recreate** the release tags on the new commit or cut a **patch version** (e.g. `2.0.9`) and new tags so Actions picks up OIDC.

### Fallback: API token instead of OIDC

If you cannot use trusted publishing, edit the **Publish to PyPI** step in the workflow to pass a secret, for example:

```yaml
uses: pypa/gh-action-pypi-publish@release/v1
with:
  packages-dir: dist/
  password: ${{ secrets.PYPI_OPENFDD_TOKEN }}
```

Use a **project-scoped** PyPI token for the matching project. Empty or wrong secret still yields **403**.

### If CI shows `HTTPError: 403 Forbidden`

- **OIDC not configured** on the PyPI project for that **exact** workflow filename, or publisher still **pending**.
- **Wrong workflow name** in PyPI (typo vs `publish-open-fdd.yml` / `publish-openfdd-engine.yml`).
- **Tag points to an old commit** that used `twine` + missing secrets — merge OIDC workflows and re-tag.
- **Version already exists** on PyPI — bump version and use a new tag.

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
- **CI upload:** same **Trusted Publishing** setup as above (workflow **`publish-openfdd-engine.yml`** on this repo). Optional **token fallback** is documented in §1.

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
