---
title: Secrets and auth
parent: Security
nav_order: 2
---

# Secrets and auth

## Files (gitignored)

| File | Contents |
|------|----------|
| `workspace/auth.env.local` | JWT secret, role passwords |
| `infra/ansible/secrets/<host>.env.local` | SSH deploy secrets (maintainers) |

Copy from `*.example` templates only.

## Required variables (production)

| Variable | Purpose |
|----------|---------|
| `OFDD_AUTH_SECRET` | HMAC signing (32+ chars) |
| `OFDD_INTEGRATOR_USER` / `PASSWORD` | Rule Lab, bindings |
| `OFDD_OPERATOR_USER` / `PASSWORD` | Operations |

## GHCR pulls

Use read-only registry credentials on edge if images are private; rotate tokens periodically.

## Backup

Back up `workspace/data/` and auth env in secure operator vault — not in git.
