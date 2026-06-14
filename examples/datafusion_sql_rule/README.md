# DataFusion SQL rule example (optional extra)

Install:

```bash
pip install -e ".[datafusion]"
```

Run against synthetic telemetry:

```bash
python examples/datafusion_sql_rule/run_example.py
```

The SQL reads from the registered Arrow table `telemetry` and must return a boolean column named `fault`.
