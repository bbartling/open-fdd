# openfdd-engine

**Install the rules engine from PyPI with the main package name:**

```bash
pip install open-fdd
```

Use **`open_fdd.engine`** (`RuleRunner`, `load_rule`, …) and optionally **`open_fdd.reports`**. See [open-fdd on PyPI](https://pypi.org/project/open-fdd/) and [online docs](https://bbartling.github.io/open-fdd/).

---

This directory builds an **optional** distribution **`openfdd-engine`** (import **`openfdd_engine`**) — a thin re-export that **depends on `open-fdd`**. It is **not** the primary release artifact; maintainers may publish it as a **second PyPI project** only if they create that project and wire CI. For most users: **`pip install open-fdd`** is the correct one-liner.

## Optional local / editable install

From the repository:

```bash
cd packages/openfdd-engine
pip install -e .
```

**`column_map`** is a plain dict or manifest — optional **`brick:`** fields in example YAML are not required (see [Column map resolvers](https://github.com/bbartling/open-fdd/blob/master/docs/column_map_resolvers.md)).

## API (subset of `open_fdd.engine`)

- `RuleRunner`, `load_rule()`, `bounds_map_from_rule()`
- `ColumnMapResolver`, `ManifestColumnMapResolver`, `FirstWinsCompositeResolver`, `load_column_map_manifest`

Rule authoring: [Expression rule cookbook](https://github.com/bbartling/open-fdd/blob/master/docs/expression_rule_cookbook.md)
