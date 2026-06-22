# Rust login screen verification

## Prerequisites

1. Generate auth credentials: `openfdd_edge auth init --path workspace/auth.env.local`
2. Start stack: `./scripts/openfdd_edge_bootstrap.sh` or `docker compose up -d --build`

## Expected UI behavior

1. Open `http://127.0.0.1:8080/` in a browser.
2. When no valid token exists, a **Sign in** page is shown (username + password).
3. There are **no** one-click role buttons and no self-mint login paths.
4. Sign in with:
   - Username: `integrator`
   - Password: value of `OFDD_INTEGRATOR_PASSWORD` in `workspace/auth.env.local`
5. After login, the header shows:
   - logged-in user (`integrator`)
   - role (`integrator`)
   - auth required flag from `/api/health`
   - API online/offline status
6. **Logout** clears the token and returns to the login screen.
7. Expired or invalid tokens redirect to login with a clear message.

## Manual API parity check

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" | jq .
```

Response must include `token`, `token_type`, `expires_at`, `role`, and `subject`.

## Security notes

- Tokens are stored in `localStorage` for this local edge UI (acceptable for OT-LAN edge use).
- Do not share `workspace/auth.env.local` or commit it to git.
- Rotate credentials with `openfdd_edge auth init --force` and recreate containers.
