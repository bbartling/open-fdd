# Testing (open-fdd engine)

This repository is the **PyPI rules engine** (`open-fdd`). Integration tests for the **Docker AFDD stack** live in [open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack) (`scripts/bootstrap.sh --test`).

## Quick run

```bash
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

Same commands run in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Optional: full stack checks

Clone **open-fdd-afdd-stack**, install the engine in editable mode from a local checkout if you are co-developing, then:

```bash
cd open-fdd-afdd-stack
./scripts/bootstrap.sh --test
```

See that repo’s README for modes (`collector`, `model`, `engine`, `full`).
