# Bench validation (Linux field / GHCR pull)

Use this on a **bench machine** that pulls `ghcr.io/bbartling/openfdd-edge-rust` — no git clone required for validation runs.

## Quick gate

```bash
cd ~/open-fdd
cp workspace/bench/data.env.local.example workspace/data.env.local
# Set OPENFDD_HAYSTACK_PASS (Niagara HTTP Basic), then:
./scripts/openfdd_bench_safe_restart.sh   # when shipped; else openfdd_rust_site_update.sh
OPENFDD_DRIVERS_VALIDATE_STRICT=1 OPENFDD_EXPECT_VERSION=3.2.4 \
  ./scripts/openfdd_drivers_validate.sh
```

Strict gate expects: Modbus live, BACnet commission read, Haystack password set + test OK, JSON API `configured: true`, SPARQL catalog 200 or SKIP on older images.

## Triage: harness vs product vs operator

| Symptom | Likely cause |
|---------|----------------|
| Haystack FAIL, `password_set: false` | Operator — set `OPENFDD_HAYSTACK_PASS` in `workspace/data.env.local` |
| JSON API `not_configured` | Set `OPENFDD_JSON_API_URL` + restart bridge (3.2.4+ seeds endpoints on startup) |
| SPARQL 404 | Older image — gate **SKIP**s; not a driver FAIL |
| Fault rule PATCH rejected | Product — use `PATCH /api/rules/{rule_id}` or `PATCH /api/fdd-rules/{rule_id}` (3.2.4+) |
| MCP “missing tools” | Harness — expect `openfdd_*` tool names per [mcp/README.md](../mcp/README.md) |
| Modbus read FAIL but JSON has values | Harness jq gate — check response shape |

## Fault rule param change (hour test minute 30)

```bash
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"confirmation_seconds":600}' \
  http://127.0.0.1:8080/api/rules/oa_temp_out_of_range
```

## References

- Driver validate: `./scripts/openfdd_drivers_validate.sh`
- Bench profile template: `workspace/bench/bench_profile.toml`
- Haystack + SPARQL model: [modeling/haystack_dashboard_model.md](modeling/haystack_dashboard_model.md)
