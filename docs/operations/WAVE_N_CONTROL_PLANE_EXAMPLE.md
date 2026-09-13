# Wave N — example control-plane files (no secrets)

Copy onto the Railway volume under `/workspace/openfdd/control_plane/` after backup.
Set passwords via Railway env vars referenced by `password_env` — **never** commit real passwords.

## tenants.json

```json
{
  "tenants": [
    { "id": "acme", "name": "ACME", "building_ids": ["ACME"] },
    { "id": "building_100", "name": "Building 100", "building_ids": ["BUILDING_100"] },
    { "id": "lakeside_sd", "name": "Lakeside / Creekside School District", "building_ids": ["LAKESIDE_ES"] }
  ]
}
```

## users.json

```json
{
  "users": [
    {
      "username": "acme-ops",
      "role": "operator",
      "tenant_ids": ["acme"],
      "password_env": "OPENFDD_USER_ACME_OPS_PASSWORD"
    },
    {
      "username": "acme-agent",
      "role": "operator",
      "tenant_ids": ["acme"],
      "password_env": "OPENFDD_USER_ACME_AGENT_PASSWORD"
    },
    {
      "username": "b100-ops",
      "role": "operator",
      "tenant_ids": ["building_100"],
      "password_env": "OPENFDD_USER_B100_OPS_PASSWORD"
    },
    {
      "username": "b100-agent",
      "role": "operator",
      "tenant_ids": ["building_100"],
      "password_env": "OPENFDD_USER_B100_AGENT_PASSWORD"
    },
    {
      "username": "lakeside-ops",
      "role": "operator",
      "tenant_ids": ["lakeside_sd"],
      "password_env": "OPENFDD_USER_LAKESIDE_OPS_PASSWORD"
    },
    {
      "username": "lakeside-agent",
      "role": "operator",
      "tenant_ids": ["lakeside_sd"],
      "password_env": "OPENFDD_USER_LAKESIDE_AGENT_PASSWORD"
    }
  ]
}
```

Hub `admin` remains `OPENFDD_ADMIN_PASSWORD` with empty `tenant_ids` (no buildings owned).
