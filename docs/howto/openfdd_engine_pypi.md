---
title: Publish openfdd-engine to PyPI
parent: How-to Guides
nav_order: 20
---

# Publish openfdd-engine to PyPI

Open-FDD publishes the standalone Pandas/YAML engine as `openfdd-engine`, separate from the full platform stack.

## Package location

- `packages/openfdd-engine`

## Local build check

```bash
cd packages/openfdd-engine
python -m pip install --upgrade pip
pip install build twine
python -m build
twine check dist/*
```

## GitHub Actions release

- Workflow: `.github/workflows/publish-openfdd-engine.yml`
- Trigger:
  - manual `workflow_dispatch`, or
  - git tag matching `openfdd-engine-v*`
- Required secret:
  - `PYPI_OPENFDD_ENGINE_TOKEN`

## Scope policy

- Publish engine package only.
- Keep full Open-FDD platform orchestration in this repository and Docker stack.

