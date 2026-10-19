# NF portal checkpoint

Lab probe for a Normal Framework portal. Point selection is explicit UUIDs
(`NF_POINT_UUIDS`), never display names.

```bash
# chmod 600 scripts/nf/.env — never commit
cp scripts/nf/.env.example scripts/nf/.env
# fill NFURL, NF_CLIENT_ID, NF_CLIENT_SECRET, and NF_POINT_UUIDS
python3 -m pip install -r scripts/nf/requirements.txt
python3 scripts/nf/read_sensors.py
```

Or export those variables in the shell (no `.env` file).

`NF_POINT_UUIDS` is a comma-separated list of provider point ids. Example maps
live in `provider_sites.bosspi.example.json` (`provider_point_id`) and
`bosspi_semantic_meta.json` (`point_id`).

Product path is the Rust `DataProvider` NF driver ([Wave-NF plan](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)). This script is the human/agent smoke only. History reads on the product path are `GET /api/v1/point/data`.
