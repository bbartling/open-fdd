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

{"username": "admin", "password": "..."}
```

Central product logins (when `OPENFDD_JWT_SECRET` is set):

| Username | Password env | JWT role |
| --- | --- | --- |
| `admin` | `OPENFDD_ADMIN_PASSWORD` | admin |
| `agent` | `OPENFDD_AGENT_PASSWORD` | operator |

Response includes JWT `token` (or `access_token`). Prefer **agent** for MCP / Cursor; keep admin for the browser UI.

## Mint short-lived agent token (admin)

```http
POST /api/auth/agent-token
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{"ttl_secs": 3600}
```

Returns an **operator** JWT (`sub=agent`). `ttl_secs` defaults to 3600 and is clamped to 60–86400.

## Session

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/auth/status` | Public | Auth enabled? `agent_login_configured`? |
| GET | `/api/auth/me` | JWT | Current user |
| POST | `/api/auth/agent-token` | Admin JWT | Mint operator JWT for MCP |

## Public routes (no JWT)

- `GET /api/health`, `GET /health`
- `GET /api/building/snapshot`, `GET /api/dashboard/summary`
- `POST /api/auth/login`, `GET /api/auth/status`

## Credentials

Set secrets in the deployment environment (Railway Variables, Compose env). Never commit or log secrets or JWTs.

{: .warning }
Do not expose the API on the public internet without TLS and network controls. On Railway, keep central and MCP private; put only web on a public domain.
