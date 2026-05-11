# CSV driver — reference

Legacy: `open_fdd/platform/drivers/csv_driver.py`, gateway `POST /ingest/csv`, `POST /ingest/csv/upload`.

Encoding sniff: UTF-16 BOM, tab sep, `ts` timestamp column patterns.

Tests: `open_fdd/tests/platform/test_csv_driver_encoding.py`, `open_fdd/tests/desktop/test_ingest_service.py`.
