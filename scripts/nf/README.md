# NF portal checkpoint (bosspi)

Lab probe for Normal Framework Online → Cloudflare tunnel → bosspi sensors.
Copied from `sparql-playground/.../part-02-nf-edge-sensors/checkpoint` for Wave-NF.

```bash
# chmod 600 scripts/nf/.env — never commit
cp scripts/nf/.env.example scripts/nf/.env
# fill NFURL + NF_CLIENT_ID + NF_CLIENT_SECRET from NF site Settings → Authorization
python3 -m pip install -r scripts/nf/requirements.txt
python3 scripts/nf/read_sensors.py
```

Or export `NFURL` / `NF_CLIENT_ID` / `NF_CLIENT_SECRET` in the shell (no `.env` file).
Pass the point display names to print as `OPENFDD_NF_SENSOR_NAMES` (comma-separated). The script does not embed a site sensor list.

**Validated 2026-10-18:** tunnel + OAuth + `POST /api/v1/point/query` returned the lab analog inputs configured for that portal.

Product path is the Rust `DataProvider` NF driver ([Wave-NF plan](../../.cursor/plans/nf_portal_ingest_mega_rev_20261018.plan.md)). This script is the human/agent smoke only.
