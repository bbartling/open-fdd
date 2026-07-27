# Merge Open-FDD ECM Engineering into `bbartling/open-fdd`

This ZIP is a **drop-in source tree for the existing `open-fdd` PyPI project**.
It is not intended to create a second public project name.

## 1. Copy the package

Copy:

```text
open_fdd/ecm_engineering/
```

into the existing Python package tree so imports become:

```python
from open_fdd.ecm_engineering import ECMJob, calculate, crosscheck
```

## 2. Copy tests and examples

Merge the included `tests/` and `examples/` files into the repository.

## 3. Ensure package data is included

The PyPI wheel/sdist must contain:

```text
open_fdd/ecm_engineering/data/Open_FDD_ECM_Engineering_Toolkit.xlsx
open_fdd/ecm_engineering/data/open_fdd_model.json
```

If Open-FDD uses setuptools package-data configuration, add the equivalent of:

```toml
[tool.setuptools.package-data]
"open_fdd.ecm_engineering" = ["data/*.xlsx", "data/*.json"]
```

If the repository already has a package-data table, merge this entry rather than replacing it.

## 4. Optional web dependencies

The core ECM code has no third-party runtime dependency. The FastAPI example is optional.
A project extra can be added if desired:

```toml
[project.optional-dependencies]
ecm-web = ["fastapi>=0.115", "uvicorn>=0.34"]
```

## 5. Public API convenience export

Optionally re-export from `open_fdd/__init__.py`:

```python
from open_fdd.ecm_engineering import ECMJob
```

This is not required; the explicit import is clearer and safer:

```python
from open_fdd.ecm_engineering import ECMJob
```

## 6. Release / PyPI

Do **not** create a second `open-fdd-ecm` PyPI project unless you deliberately want a separate distribution.
The existing `open-fdd` distribution is already published from `bbartling/open-fdd`, so the clean approach is:

1. merge this source tree;
2. ensure package data is included;
3. run tests;
4. bump the Open-FDD version;
5. use the repository's existing Trusted Publishing release workflow.

## 7. Smoke test before release

```bash
python -m pytest tests/test_algorithms.py tests/test_job.py -q
```

Then build the existing Open-FDD distribution and inspect the wheel:

```bash
python -m build
python -m zipfile -l dist/*.whl | grep ecm_engineering
```

The wheel listing should include the `.xlsx` and `.json` data files.

## 8. Example after `pip install open-fdd`

```python
from open_fdd.ecm_engineering import ECMJob

job = (
    ECMJob("Lincoln Middle School")
    .set_global(area_ft2=85000, electric_rate=0.145, gas_rate=0.92)
    .add_ecm(
        "static_pressure_reset",
        fan_kw=55.9,
        hours=4100,
        baseline_speed=0.82,
        proposed_speed=0.67,
    )
)

job.save("Lincoln_Middle_School_ECMs.xlsx")
```
