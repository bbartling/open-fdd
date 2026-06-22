# Rust edge authentication

See `feature/rust-auth-security-parity` for full username/password JWT auth.

Bootstrap generates `workspace/auth.env.local` with:

- `OFDD_OPERATOR_USER` / `OFDD_OPERATOR_PASSWORD`
- `OFDD_INTEGRATOR_USER` / `OFDD_INTEGRATOR_PASSWORD`
- `OFDD_AGENT_USER` / `OFDD_AGENT_PASSWORD`
- `OFDD_AUTH_SECRET`

## Rules

- `chmod 600 workspace/auth.env.local`
- Never commit auth files
- Never print secrets in logs or agent chat
- Rotate: regenerate auth file and `docker compose up -d --force-recreate`

Auth is local edge app security — not a substitute for OT network segmentation.
