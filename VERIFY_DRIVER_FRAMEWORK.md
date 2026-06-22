# Verify driver framework

## Schema envelope

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"sub":"ci","role":"agent"}' | jq -r .access_token)

curl -s http://localhost:8080/api/drivers/tree \
  -H "Authorization: Bearer $TOKEN" | jq '{
    schema_version,
    generated_at,
    source,
    generated_from_demo_fixture,
    validation,
    provenance
  }'
```

Required fields: `schema_version`, `generated_at`, `source`, `validation.ok`.

## Workspace health

```bash
curl -s http://localhost:8080/api/health/workspace \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Expect `writable: true` for a healthy local install.

## Driver health

```bash
curl -s http://localhost:8080/api/bacnet/driver/health \
  -H "Authorization: Bearer $TOKEN" | jq '.protocol_proof, .validation'
```

## Unit tests

```bash
cargo test --workspace
```

See also:

- `DRIVER_TREE_SCHEMA.md`
- `DRIVER_STORAGE_DESIGN.md`
- `VERIFY_BACNET_REAL_VS_SIMULATED.md`
