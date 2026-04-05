# Examples (`open-fdd`)

Everything here uses the **engine only** (`pip install open-fdd`): **pandas** + **YAML rules** + optional **`column_map`** manifests. No Docker.

## Quick: Brick, Haystack, DBO, or 223P naming

One script, pick how you name sensors in rule YAML vs DataFrame columns:

```bash
cd /path/to/open-fdd   # repo root
pip install open-fdd   # or: pip install -e .

python examples/column_map_resolver_workshop/run_ontology_demo.py --list
python examples/column_map_resolver_workshop/run_ontology_demo.py brick
python examples/column_map_resolver_workshop/run_ontology_demo.py haystack
python examples/column_map_resolver_workshop/run_ontology_demo.py dbo
python examples/column_map_resolver_workshop/run_ontology_demo.py 223p
```

| Mode | What it shows |
|------|----------------|
| **`brick`** | Brick class names → your columns `sat` / `oat` |
| **`minimal`** | Same Brick rule, smallest manifest (supply air only) |
| **`haystack`** | Haystack-style slugs (e.g. `discharge_air_temp_sensor` → `sat`) |
| **`dbo`** | DBO / Google Digital Buildings–style names (e.g. `SupplyAirTemperatureSensor` → `sat`) |
| **`223p`** | Scoped slugs safe for **`type: expression`** (e.g. `ahu1_supply_air_temp` → `sat`) |

Details and file list: **[`column_map_resolver_workshop/README.md`](column_map_resolver_workshop/README.md)**.

**Compare key shapes only** (no full rule run):

```bash
python examples/column_map_resolver_workshop/demo_multi_ontology_illustration.py
```

## AHU notebooks and CSVs

Folder **`AHU/`**: sample **`rules/*.yaml`**, **`RTU11.csv`**, **`AHU7.csv`**, and Jupyter notebooks. Open locally after `git clone` (see **`AHU/`** — no single CLI entrypoint).

## Full Docker platform

Compose, API, and UI examples live in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

## Docs on the web

- [Examples (repository)](https://bbartling.github.io/open-fdd/examples) — engine docs index  
- [Column map & resolvers](https://bbartling.github.io/open-fdd/column_map_resolvers)  
- [Engine-only & IoT](https://bbartling.github.io/open-fdd/howto/engine_only_iot)
