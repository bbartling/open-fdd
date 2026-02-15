# Cloud export example

Pull fault and timeseries data from the Open-FDD API. Use this as a **starting point** for how your cloud or MSI integration can get Open-FDD data to your platform (replace the script’s output with your own send logic: REST POST, S3, IoT Hub, etc.). See the docs: [Concepts → Cloud export example](https://github.com/bbartling/open-fdd/blob/master/docs/concepts/cloud_export.md).

## Run locally

```bash
pip install httpx
python examples/cloud_export.py
python examples/cloud_export.py --site default --days 14
API_BASE=http://your-openfdd:8000 python examples/cloud_export.py
```

## Run in Docker

From repo root (build context = . so examples/ is available):

```bash
docker build -t openfdd-cloud-export -f examples/cloud_export/Dockerfile .
docker run --rm -e API_BASE=http://host.docker.internal:8000 openfdd-cloud-export
```

On Linux use `http://172.17.0.1:8000` or your host IP if host.docker.internal is unavailable.

Or add to your compose — point `API_BASE` at the open-fdd API service.

## What it does

1. **GET /download/faults?format=json** — fault results for MSI/cloud ingestion
2. **GET /download/faults?format=csv** — fault CSV (Excel-friendly)
3. **GET /analytics/motor-runtime** — motor runtime (data-model driven; no fan point = NO DATA)
4. **GET /download/csv** — timeseries wide-format CSV
5. **GET /analytics/fault-summary** — fault counts by fault_id

Replace the `print()` calls with your cloud integration: Azure IoT Hub, AWS, SkySpark, custom REST, etc.
