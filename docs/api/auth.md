---
title: Authentication
parent: API Reference
nav_order: 1
---

# Authentication

## Login

```http
POST /api/auth/login
Content-Type: application/json

{"username": "integrator", "password": "..."}
```

Response includes JWT `token` (or `access_token`).

## Session

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/auth/status` | Public | Auth enabled? |
| GET | `/api/auth/whoami` | JWT | Current user |
| POST | `/api/auth/logout` | Public | Invalidate session |

## Public routes (no JWT)

- `GET /api/health`, `GET /health`
- `GET /api/building/snapshot`, `GET /api/building/status`
- `GET /api/ingest/contract`
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/status`

## Credentials

Integrator password is generated in `workspace/auth.env.local` at bootstrap. Never commit or log secrets.

{: .warning }
Do not expose the API on the public internet without TLS and network controls.
