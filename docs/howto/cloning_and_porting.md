---
title: Cloning and porting
parent: How-to guides
nav_order: 15
---

# Cloning and porting

The **open-fdd** repository should be portable across workstations and CI images: clone, create a virtual environment, **`pip install -e ".[dev]"`**, run **`pytest`**.

## What transfers cleanly

- Automated tests (`open_fdd/tests`, CI in `.github/workflows/ci.yml`)
- Example rules under **`examples/`** and **`open_fdd/tests/fixtures/rules/`**
- Documentation under **`docs/`**

## What changes per deployment

- Paths to CSV or Parquet inputs
- **`column_map`** from your naming convention to DataFrame columns
- Optional Brick TTL or SQL metadata **you** maintain outside this package

## Recommended first pass on a new machine

1. `git clone` and `pip install -e ".[dev]"`
2. `python -c "import open_fdd; print('open_fdd OK')"`
3. `pytest`
4. Run a small example from **`examples/README.md`**

## Portability goal

Another engineer should be able to reproduce rule behavior from **version-controlled YAML** and a **documented data sample**, without private containers or undisclosed APIs.
