# Testing (open-fdd engine)

This repository is the **PyPI rules engine** (`open-fdd`). Integration tests for the **Docker AFDD stack** live in [open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack) (see that repo’s README and CI).

---

## 1. Local install + tests

```bash
cd open-fdd
python3 -m venv env
source env/bin/activate                 # Windows: env\Scripts\activate
pip install -U pip
pip install -e ".[test]"
python -c "import importlib.metadata as m; print('open-fdd', m.version('open-fdd'))"
python -m pytest
```

---

## 2. Run all `examples/` smoke scripts

From the **repo root** with **`env` activated** (step 1 above) and **`open-fdd` installed** (`pip install .` or `pip install -e .`; use `pip install -e ".[test]"` if you need pytest).

**Column map workshop** — from the **repo root** (`cd open-fdd`, `env` activated):

```bash
cd open-fdd
source env/bin/activate

python examples/column_map_resolver_workshop/simple_ontology_demo.py
```

**Not covered here:** Jupyter notebooks under **`examples/AHU/`** (open in Jupyter; they use local CSVs and helpers). **`examples/README.md`** lists entrypoints.

---

## 3. GitHub Actions vs local testing

| Workflow | When it runs | What it does |
|----------|----------------|--------------|
| **CI** ([`ci.yml`](.github/workflows/ci.yml)) | PR + push to `master` | `pip install -e ".[test]"`, `python -m pytest`, docs text build |
| **Docs PDF** ([`docs-pdf.yml`](.github/workflows/docs-pdf.yml)) | Push to `master` changing `docs/**` or the script; or manual dispatch | Rebuilds `pdf/open-fdd-docs.pdf` + `pdf/open-fdd-docs.txt` and opens a PR if they differ from `master` |
| **Publish `open-fdd`** ([`publish-open-fdd.yml`](.github/workflows/publish-open-fdd.yml)) | Push tag `open-fdd-v*` or manual dispatch | `python -m build`, `twine check`; **PyPI upload only on tag `open-fdd-v*`** |

---

## 4. Releasing a new version to PyPI (`open-fdd`)

PyPI rejects re-uploading the same version, so every release needs a **version bump** in source control.

1. Bump **`version`** in [`pyproject.toml`](pyproject.toml) under `[project]` (e.g. `2.0.14` → `2.0.15`).
2. Commit and push to `master` (or your release branch policy).
3. Create an **annotated** tag whose suffix **exactly** matches that version:

   ```bash
   git tag -a open-fdd-v2.0.15 -m "open-fdd 2.0.15"
   git push origin open-fdd-v2.0.15
   ```

The publish workflow checks that the tag matches `pyproject.toml` **version**. Manual **workflow_dispatch** builds and checks artifacts; upload still requires the tag (see the workflow `if:` on the publish step).
