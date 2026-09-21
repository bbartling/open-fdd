---
title: API & Security
layout: default
nav_order: 8
has_children: true
permalink: /api/
---

# API & Security

JWT-protected REST on **central** (`/api/*`). The React SPA proxies same-origin. Optional **MCP** stdio tools call the same API.

| Guide | Content |
|-------|---------|
| [Authentication](auth.html) | Login, roles, agent tokens |
| [Routes](routes.html) | REST route map |
| [Security reporting](../security.html) | Private vulnerability reporting + posture |

Discover agent tools: `GET /api/agent/tools` (Bearer JWT).
