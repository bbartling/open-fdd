# ACME compaction APPLY (`wave_u_acme_compaction_apply_20260923T125014Z`)

| Metric | Value |
|--------|-------|
| Hub | https://openfdd-web-production-af99.up.railway.app |
| Before (plan_only) | plans=40 files=54814 bytes=86694071 |
| After (plan_only) | plans=0 files=0 bytes=0 |
| APPLY ok | true |
| Partitions compacted | 40 |
| Input files collapsed | 54814 |
| Input bytes | 86694071 (~82.7 MiB) |
| Output bytes | 1651755 (~1.6 MiB) |
| OPENFDD_PARQUET_FLUSH_SECONDS | set to **300** on central (redeploy with AFDD pin) |

Hard gate for continuous AFDD: **PASS** (eligible multi-part plans = 0 after APPLY).
