# Rust edge authentication verification

This checklist validates the 100% Rust auth stack on `feature/rust-auth-security-parity`.

## Generate credentials

```bash
cd edge
cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local
chmod 600 ../workspace/auth.env.local
```

Existing files are preserved unless `--force` is passed.

Lab-only secret display:

```bash
cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local --show-secrets
```

## Bootstrap edge stack

```bash
./scripts/openfdd_edge_bootstrap.sh
```

Options:

- `--force-auth` regenerates `workspace/auth.env.local`
- `--show-secrets` prints redacted values unless explicitly requested for lab use

After rotating credentials, recreate containers so Docker reloads `env_file`:

```bash
docker compose up -d --force-recreate
```

## Test login without printing passwords

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" | jq '{ok, role, subject, expires_at}'
```

## Protected routes

```bash
TOKEN="<token from login>"
curl -s http://127.0.0.1:8080/api/health | jq '.auth_required'
curl -s http://127.0.0.1:8080/api/health/stack -H "Authorization: Bearer $TOKEN" | jq '.ok'
```

Public `/api/health` must work without a token and report `auth_required: true`.

## Negative tests

Self-mint must fail:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' -d '{"sub":"agent","role":"agent"}'
# expect 401
```

Wrong password must fail without leaking which field was wrong.

## RBAC

Run the automated smoke script:

```bash
bash scripts/verify_rust_auth_smoke.sh
```

Checks:

- operator cannot POST `/api/modbus/scan` (403)
- agent cannot POST `/api/bacnet/write` even with `approved=true` (403)
- integrator can reach `/api/health/stack`

## Audit log

Security events append to `workspace/logs/auth_audit.jsonl`. Passwords, JWTs, and secrets are redacted.

## Network posture

Open-FDD edge auth is local OT-LAN application security. Do not expose port 8080 directly to the public internet. Prefer VPN, Tailscale, or a reverse proxy with TLS and network segmentation.

## Troubleshooting JWT expired

Sign in again from the dashboard or POST `/api/auth/login`. Default TTL is `OFDD_JWT_TTL_SECONDS=28800` (8 hours).

## Rust tests

```bash
cd edge && cargo test
```
