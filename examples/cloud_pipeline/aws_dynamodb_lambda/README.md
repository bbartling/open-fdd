# AWS Lambda reference (optional)

This folder is a **reference pattern only** — not part of the core PyPI story.

For production AWS deployments:

1. Lambda reads DynamoDB/stream batches
2. Convert to PyArrow Table
3. Call `open_fdd.arrow_runtime.run_arrow_rule`
4. Emit faults to EventBridge, SQS, or DynamoDB

Implement `lambda_function.py` in your own repo with IAM and packaging; keep `open-fdd` as a Lambda layer or vendored wheel.
