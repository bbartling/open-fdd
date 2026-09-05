# Example qualification report (redacted)

Schema: `openfdd_qualification_manifest_v1`

Illustrative only — do not treat as a live PASS for a candidate.

```json
{
  "schema_version": "openfdd_qualification_manifest_v1",
  "run_id": "nightly-ot-bench_EXAMPLE",
  "environment_class": "railway_field",
  "hub_base": "https://openfdd-web-production-af99.up.railway.app",
  "candidate": { "source_sha": "3.3.26+REDACTED", "image_tag": "sha-REDACT" },
  "required_gates": [
    "00_hub_health_edges", "01_synth59", "02_gate17", "03_b100",
    "04_creekside", "05_gate19", "06_zap_baseline", "07_auth_role_matrix",
    "08_mcp_accuracy"
  ],
  "gates": {
    "00_hub_health_edges": { "status": "PASS" },
    "01_synth59": { "status": "PASS" },
    "02_gate17": { "status": "PASS" },
    "03_b100": { "status": "PASS" },
    "04_creekside": { "status": "PASS" },
    "05_gate19": { "status": "PASS", "notes": "structural READY ≠ ML completeness" },
    "06_zap_baseline": {
      "status": "PASS",
      "coverage": "public baseline only; not authenticated AF"
    },
    "07_auth_role_matrix": { "status": "PASS" },
    "08_mcp_accuracy": { "status": "PASS" }
  },
  "overall": {
    "status": "PASS",
    "fully_qualified": true,
    "reason": "all required gates PASS (or NOT_APPLICABLE)"
  }
}
```

Counter-example: `SKIP_ZAP=1` records `06_zap_baseline=SKIPPED` → `fully_qualified=false`, `overall.status=BLOCKED`.
