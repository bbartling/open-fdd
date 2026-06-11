# Generic IoT → FDD → fault sink

Shows how a cloud or edge-adjacent worker can:

1. Read telemetry rows from an external source (fake here)
2. Build a PyArrow Table
3. Run `apply_faults_arrow` via `open_fdd.arrow_runtime`
4. Write fault events to an external sink (fake here)

No AWS/Docker required. See `aws_dynamodb_lambda/` for an optional reference layout only.

```bash
pip install open-fdd
python run_fdd_batch.py
```
