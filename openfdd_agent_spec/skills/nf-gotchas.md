---
name: nf-gotchas
description: Known NF 3.10 traps (existing-uuid overwrite, delete, portal 401, TLS, logged secrets) and how to avoid them.
---
# NF gotchas: read before touching a live box

Full list with workarounds: `docs/operations/nf/nf-gotchas.md`. The ones that bite agents:

1. **Never pass an existing point uuid to `POST /api/v1/bacnet/local`.** It overwrites that point. Omit `uuid`.
2. **No layer-scoped delete.** MCP `delete_points` removes every layer; back up first, overwrite instead of delete.
3. **Portal vs LAN.** API-key tokens get 401 on `/api/v1/bacnet/*` through Normal Online; use the LAN. App pages need
   the Clerk `ConsoleJWT` through the portal.
4. **Empty-body 403 on `/api/v1/auth/token`** is intermittent: retry.
5. **Do not enable `TAILSCALE_HTTPS`**: it breaks hooks and the portal tunnel. Use `deploy/nf-caddy`.
6. **NF logs the backup SAS URL in plain text.** Never paste `docker logs`, `nf version` or env dumps; redact `BACKUP_URL`.
7. **BACnet server types**: no CharacterString/Date/DateTime objects; a multi-state PV is typed Enumerated (strict
   clients cannot read it). Put text in Haystack tags.
8. **Imported points do not poll until a period is set**; point markers are not derived from `class`.
9. Static app files are cached 5 minutes: reload with `?v=N`.

When a new trap shows up, add it to `docs/operations/nf/nf-gotchas.md` in the same PR.

10. **Missing app-file GET may be HTTP 500** (`Content-Type: application/grpc`, empty body), not 404. The hand-edit
    guard treats that signature as missing **only** for paths that are new relative to the box (not in the app
    `files` list, or not in the last push manifest when that list is unavailable). Every other 500 still aborts.
11. **StartHook args are a string-to-string map.** JSON arrays (e.g. `uuids`) and numeric-looking fields (`windowHours`)
    arrive as strings. Coerce before use (`history.js` `normalizeArgs`; see #1559 for a shared helper).
12. **Windows cp1252 consoles.** Hook event text can contain non-cp1252 Unicode; `report_run` must use the safe
    print path or verify aborts after a successful install (#1560).
13. **UpdatePoints merges point attributes.** An omitted attribute can survive a result update. Write every
    Open-FDD result attribute and send an empty string for values that do not apply. Treat an empty or missing
    value the same when reading. A disposable NF 3.10.9-1 lab stored empty strings and normalized null
    attribute values to empty strings (#1563).
14. **Large history URLs can fail at the NF front door.** Keep UUID lists bounded and merge history chunks
    before rendering. The HTTP mock enforces a request-size limit (#1571).
15. **Timescale runtime roles cannot migrate installer-owned objects.** Check the schema before uploading app
    files and apply migrations as the installer role when needed (#1570).
