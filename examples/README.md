# Examples (`open-fdd`)

Everything here uses the **engine only** (`pip install open-fdd`): **pandas** + **YAML rules** + optional **`column_map`**. No Docker.

## Quick: one rule, many ontology key styles

One YAML rule (cookbook-style `inputs`) and one script that runs it five times with a different `column_map` key each time (Brick, Haystack, DBO, 223P):

```bash
cd /path/to/open-fdd   # repo root
pip install open-fdd   # or: pip install -e .

python examples/column_map_resolver_workshop/simple_ontology_demo.py
```

Details: **[`column_map_resolver_workshop/README.md`](column_map_resolver_workshop/README.md)**.

## AHU notebooks and CSVs

Folder **`AHU/`**: sample **`rules/*.yaml`**, **`RTU11.csv`**, **`AHU7.csv`**, and Jupyter notebooks. Open locally after `git clone` (see **`AHU/`** — no single CLI entrypoint).

## Full Docker platform

Compose, API, and UI live in **`afdd_stack/`** in this repository (`./scripts/bootstrap.sh`).

## Docs on the web

- [Examples (repository)](https://bbartling.github.io/open-fdd/examples) — engine docs index  
- [Column map & resolvers](https://bbartling.github.io/open-fdd/column_map_resolvers)  
- [Engine-only & IoT](https://bbartling.github.io/open-fdd/howto/engine_only_iot)
