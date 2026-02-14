---
title: API Reference
nav_order: 13
has_children: true
---

# API Reference

Open-FDD exposes three API surfaces:

| API | Description |
|-----|-------------|
| **[Platform REST API](platform)** | HTTP API for CRUD (sites, equipment, points), data-model export/import, Brick TTL, bulk download (CSV, faults), analytics, and run-now trigger. Served at port 8000. |
| **[Engine API](engine)** | Python API for loading rules and running the FDD rule engine against pandas DataFrames. Used by the platform loop and by standalone scripts. |
| **[Reports API](reports)** | Python API for fault analytics, visualization, and report generation (text, CSV, Word). Used by analyst workflows and notebooks. |

---

## Interactive documentation

When the platform is running:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs) — try endpoints, see request/response schemas, version = installed `open-fdd` package.
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc) — read-only reference.

---

## Base URL

```
http://localhost:8000
```

Replace `localhost` with your host or IP when accessing remotely (e.g. `http://192.168.204.16:8000`).

---

## Versioning

The API follows the installed `open-fdd` package version. No version prefix in the path; breaking changes are documented in release notes.
