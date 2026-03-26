# RTU11 Example

Quick beginner example for **engine-only** workflows using real RTU data.

## What you get

- `RTU11_engine_tutorial.ipynb` — step-by-step notebook
- `run_demo.py` — simple CLI demo
- `rules/*.yaml` — small rule files
- `../data/RTU11.csv` — real sample dataset

## Install

Use either published PyPI or local editable install:

```bash
# Published package
./.venv/bin/python -m pip install --upgrade open-fdd

# OR local dev package
./.venv/bin/python -m pip install -e ".[dev]"
```

## Run

```bash
cd /path/to/open-fdd
./.venv/bin/python examples/RTU11/run_demo.py
```

For notebook:

```bash
cd /path/to/open-fdd
./.venv/bin/python -m jupyter lab
# open examples/RTU11/RTU11_engine_tutorial.ipynb
```

## Notes

- This is library/engine usage on pandas data.
- It is separate from Docker stack orchestration (`./scripts/bootstrap.sh`).
