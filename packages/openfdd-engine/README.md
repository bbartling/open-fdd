# openfdd-engine

Thin installable wrapper around **[open-fdd](https://pypi.org/project/open-fdd/)** on PyPI: same **pandas + YAML** fault-detection engine (`RuleRunner`, bounds/flatline/expression rules) without pulling in the full Docker AFDD stack.

| | |
|--|--|
| **Engine (this metapackage)** | [openfdd-engine on PyPI](https://pypi.org/project/openfdd-engine/) |
| **Core library** | [open-fdd on PyPI](https://pypi.org/project/open-fdd/) — `pip install open-fdd` also works for library-only use |
| **Full platform** | Clone the repo and run `./scripts/bootstrap.sh` for API, UI, TimescaleDB, BACnet, etc. |
| **Docs** | [open-fdd documentation](https://bbartling.github.io/open-fdd/) |

## Install

```bash
pip install openfdd-engine
```

For optional Brick TTL / SPARQL helpers used with rules:

```bash
pip install "openfdd-engine[brick]"
```

## API

- `RuleRunner` — run YAML rules on a DataFrame
- `load_rule()` / `load_rules_from_dir()`
- `bounds_map_from_rule()`
- `resolve_from_ttl()` — Brick column maps when using TTL

Rule authoring and patterns live in the main repo:

- [Expression rule cookbook](https://github.com/bbartling/open-fdd/blob/master/docs/expression_rule_cookbook.md)
- [Engine-only deployment and external IoT pipelines](https://github.com/bbartling/open-fdd/blob/master/docs/howto/engine_only_iot.md) — `RuleRunner` vs Docker `--mode engine`

## Release alignment

`openfdd-engine` versions track the thin packaging layer; **`open-fdd`** carries the engine implementation version (see `pyproject.toml` in the repo root). Use `pip install -U open-fdd openfdd-engine` to refresh both.
