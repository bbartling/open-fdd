---
title: PyPI releases (open-fdd)
parent: How-to Guides
nav_order: 20
---

# PyPI releases (`open-fdd`)

**Canonical public install for the 2.x rules engine:**

```bash
pip install open-fdd
```

That distribution ships **`open_fdd.engine`** (`RuleRunner`, YAML rules, same stack as the platform FDD loop). Legacy PyPI line **`open-fdd` 0.1.x** is a different, older package era; **2.x** is the current engine + platform-capable tree in this repository.

---

## `openfdd-engine` (optional, not the primary PyPI story)

The repo also contains **`packages/openfdd-engine/`** (import name **`openfdd_engine`**): a thin re-export that **depends on `open-fdd`**. It exists for integrators who want a separate Python distribution name, but **it is not required** for engine-only use and **is not automatically published** to PyPI from this repo. Do **not** tag `openfdd-engine-v*` unless you have intentionally created a **`openfdd-engine`** project on PyPI and configured trusted publishing for it.

CI verifies that package still builds (manual **Actions → Build openfdd-engine package** workflow).

---

## Release baseline (PyPI)

- Check live version:

```bash
curl -s https://pypi.org/pypi/open-fdd/json | python3 -c "import sys, json; print(json.load(sys.stdin)['info']['version'])"
```

---

## 1) Before a release of `open-fdd`

1. **Version** — Root **`pyproject.toml`** → `[project] version` (e.g. `2.0.11`).
2. **Optional** — If you maintain **`packages/openfdd-engine`** in lockstep, bump its `version` / `open-fdd>=…` there (source only unless you publish a second project).

### Transition checklist (legacy 0.1.x → 2.x on PyPI)

1. Confirm root `pyproject.toml` sets **`open-fdd`** to the intended **`2.x`** version.
2. Merge/push release commits to **`master`** (or your release branch).
3. Tag **`open-fdd-vX.Y.Z`** and push the tag.
4. Confirm [open-fdd on PyPI](https://pypi.org/project/open-fdd/) shows **`X.Y.Z`**.

### PyPI upload auth (`open-fdd` only)

CI uses **[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)** (OIDC from GitHub). Configure **one** trusted publisher on the **`open-fdd`** PyPI project:

1. [pypi.org](https://pypi.org) → project **`open-fdd`** → **Manage project** → **Publishing** (not Settings).
2. Add a **GitHub** trusted publisher:
   - **Owner:** `bbartling`
   - **Repository:** `open-fdd`
   - **Workflow name:** **`publish-open-fdd.yml`**
3. Save.

Workflow file: **`.github/workflows/publish-open-fdd.yml`**. Tags **`open-fdd-v*`** trigger upload. **`workflow_dispatch`** is build/check only (no upload) if configured that way.

Official guide: [Publishing with GitHub Actions OIDC](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

### Fallback: API token

If you cannot use OIDC, pass a project-scoped token, for example:

```yaml
uses: pypa/gh-action-pypi-publish@release/v1
with:
  packages-dir: dist/
  password: ${{ secrets.PYPI_OPENFDD_TOKEN }}
```

### If CI shows `invalid-publisher` or `403`

- Trusted publisher on PyPI doesn’t match the **exact** workflow filename or repository.
- Tag points to a commit **before** the OIDC workflow existed — merge fix, retag.
- **Version already on PyPI** — bump version and use a **new** tag.

---

## 2) Publish `open-fdd` (commands)

### Local dry run

```bash
cd /path/to/open-fdd   # repo root
python -m pip install --upgrade pip build twine
python -m build
twine check dist/*
```

### GitHub Actions

```bash
git checkout master   # or your release branch
# bump version in pyproject.toml, commit, push
git tag open-fdd-v2.0.11
git push origin open-fdd-v2.0.11
```

---

## 3) If you ever want a second PyPI project `openfdd-engine`

1. Create project **`openfdd-engine`** on PyPI.
2. Add trusted publisher: workflow must match whatever workflow performs the upload (restore `push: tags: openfdd-engine-v*` + `gh-action-pypi-publish` from git history if needed).
3. Tag **`openfdd-engine-v*`** only after PyPI is configured — otherwise OIDC fails with `invalid-publisher`.

---

## Scope policy

- **PyPI** ships the **Python packages** ( **`open-fdd`** is the supported public name for 2.x).
- **Full edge stack** remains **repo + Docker** (`./scripts/bootstrap.sh`).

See also: [Engine-only deployment and external IoT pipelines](engine_only_iot.md).
