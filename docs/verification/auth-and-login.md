# Auth and login verification

Validates JWT auth, generated credentials, login screen, and RBAC.

> Requires Rust edge auth on `master` (`openfdd_edge auth init`, login UI).

## Generate credentials

```bash
cd edge
cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local
chmod 600 ../workspace/auth.env.local
```

Existing files are preserved unless `--force` is passed.

Lab-only secret display (never in production logs):

```bash
cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local --show-secrets
```

## Start stack

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
# or
docker compose up -d --build
```

## Login UI

1. Open `http://127.0.0.1:8080/`
2. Sign in with integrator username/password from `workspace/auth.env.local`
3. Header shows user, role, and API health
4. **Logout** clears token and returns to login
5. Expired tokens redirect to login with a clear message

## API parity

```bash
# Public health
curl -fsS http://127.0.0.1:8080/api/health | jq '.auth_required'

# Login
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"<from-auth.env.local>"}' | jq -r .access_token)

curl -fsS http://127.0.0.1:8080/api/auth/whoami \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -fsS http://127.0.0.1:8080/api/health/stack \
  -H "Authorization: Bearer $TOKEN" | jq '.ok'
```

## RBAC expectations

| Role | Read | Create/edit | Activate rules/graphs |
| --- | --- | --- | --- |
| operator | yes | no | no |
| integrator | yes | yes | yes |
| agent | yes | propose/validate | no |

## Security notes

- `auth.env.local` must be mode `600`
- Never print passwords in bootstrap, update, or agent chat output
- BACnet/Modbus writes require integrator + explicit `approved=true`
