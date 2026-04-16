# Testing (open-fdd)

- **Engine:** `open_fdd/tests/` — run in CI with `pip install -e ".[dev]"` and `pytest`.

---

## 1. Local install + tests

```bash
cd open-fdd
python3 -m venv env
source env/bin/activate                 # Windows: env\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
python -c "import importlib.metadata as m; print('open-fdd', m.version('open-fdd'))"
python -m pytest
```

---

## 2. Run `examples/` smoke scripts

From the **repo root** with the venv activated and **`open-fdd`** installed (`pip install -e .` or `pip install -e ".[dev]"` if you need pytest).

See **`examples/README.md`** for entrypoints. Jupyter notebooks under **`examples/AHU/`** are optional.

---

## 3. GitHub Actions vs local testing

| Workflow | When it runs | What it does |
|----------|----------------|--------------|
| **CI** ([`ci.yml`](.github/workflows/ci.yml)) | PR + push to `main` / `master` / `develop` | `pip install -e ".[dev]"`, combined docs text build, **`pytest`**, `python -m build` + `twine check` for **`open-fdd`** and **`packages/openfdd-engine`** |
| **Docs PDF** ([`docs-pdf.yml`](.github/workflows/docs-pdf.yml)) | Push changing `docs/**` or the script; or manual dispatch | Rebuilds `pdf/open-fdd-docs.pdf` + `pdf/open-fdd-docs.txt` when configured |
| **Publish `open-fdd`** ([`publish-open-fdd.yml`](.github/workflows/publish-open-fdd.yml)) | Push tag `open-fdd-v*` or manual dispatch | Build and PyPI upload on matching tags |

---

## 4. Releasing a new version to PyPI (`open-fdd`)

PyPI rejects re-uploading the same version, so every release needs a **version bump** in source control.

1. Bump **`version`** in [`pyproject.toml`](pyproject.toml) under `[project]`.
2. Commit and push to `master` (or your release branch policy).
3. Create an **annotated** tag whose suffix **exactly** matches that version:

   ```bash
   git tag -a open-fdd-v2.0.15 -m "open-fdd 2.0.15"
   git push origin open-fdd-v2.0.15
   ```

The publish workflow checks that the tag matches `pyproject.toml` **version**.
