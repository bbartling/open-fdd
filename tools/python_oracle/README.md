# Python oracle tooling (CI / bench only)

**Not** part of the product request path. Product FDD is Rust/DataFusion on GHCR.

## Scripts

| Script | Role |
|--------|------|
| [`export_pandas_oracle.py`](export_pandas_oracle.py) | Run real `open_fdd.rules` on a fixture; write JSON metrics |
| [`validate_data.py`](validate_data.py) | Legacy Vibe19 entry — prefer in-repo data checks |

## Setup

```bash
pip install -e '.[oracle]'
python tools/python_oracle/export_pandas_oracle.py \
  --fixture crates/fdd_rules/fixtures/oracle/ECON-4/fault \
  --rule ECON-4 \
  --out .cache/oracle/ECON-4_fault.json
```

CI entrypoints: `scripts/sql_pandas_oracle_check.py`, `scripts/parity_inventory_check.py`.

See also [`docs/COOKBOOK_OWNERSHIP.md`](../../docs/COOKBOOK_OWNERSHIP.md).
