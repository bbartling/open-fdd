# React / no-Python stack version manifest (P1-M6-02)

| component | image / path | notes |
|---|---|---|
| SPA | `frontend/web` → `openfdd-web` (nginx) | Serves static assets; proxies `/api` to central |
| API | `services/central` → `openfdd-central` | `OPENFDD_REACT_UI=1` |
| Broker | `services/mqtt` → `openfdd-mqtt` | Optional for pure CSV/FDD lab |
| React SPA | **absent** | Not in `docker/compose.react.yml` |

Compose file: [`docker/compose.react.yml`](../../docker/compose.react.yml)

```bash
docker compose -f docker/compose.react.yml config
# health: GET http://localhost:8080/api/capabilities  (react_ui true when OPENFDD_REACT_UI=1)
# SPA:    http://localhost:3000/
```

Rollback to React: use `docker/compose.central.yml` (includes `ui` service) — routing flip is Phase 2.
