---
title: PyPI releases (open-fdd)
parent: How-to Guides
nav_order: 20
---

# PyPI releases (`open-fdd`)

**One PyPI project** — canonical install:

```bash
pip install open-fdd
```

That wheel ships:

| Module | Role |
|--------|------|
| **`open_fdd.engine`** | YAML **`RuleRunner`** on pandas (PyYAML + Pydantic in core deps) |
| **`open_fdd.playground`** | Portable **`evaluate(row, cfg, …)`** sandbox (Rule Lab / lambda style) |
| **`open_fdd.reports`** | Optional — `pip install "open-fdd[reports]"` |

**`pip install "open-fdd[engine]"`** still works (empty extra; engine deps are in the base install since 2.4.x).

**Why does PyPI “Release history” mix `0.1.x` and `2.x`?** Still **one** project: **0.1.x** was the legacy era; **2.x** is the current tree. Pip resolves latest **2.x** unless pinned.

**CI:** only **`.github/workflows/publish-open-fdd.yml`** — tag **`open-fdd-vX.Y.Z`** to upload. No separate `openfdd-engine` publish workflow.

The repo folder **`packages/openfdd-engine/`** is a **deprecated local shim** (`import openfdd_engine`); do not publish it to PyPI on new releases.

---

## Release baseline (PyPI)

- Check live version:

```bash
curl -s https://pypi.org/pypi/open-fdd/json | python3 -c "import sys, json; print(json.load(sys.stdin)['info']['version'])"
```

---

## 1) Before a release of `open-fdd`

1. **Version** — Root **`pyproject.toml`** → `[project] version` (e.g. `2.4.1`).
2. **Tests** — `pytest open_fdd/tests` green; optional `workflow_dispatch` on **Publish open-fdd** for a dry run before tagging.

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

## Scope policy

- **PyPI** = **`open-fdd`** only (engine + playground in one wheel).
- **GHCR** = edge operator images (`openfdd-bridge`, etc.) — separate workflow; see [Publish Docker addons](publish_docker_addons.md).

See also: [PyPI playground](open_fdd_playground_pypi.md), [Engine-only deployment and external IoT pipelines](engine_only_iot).
