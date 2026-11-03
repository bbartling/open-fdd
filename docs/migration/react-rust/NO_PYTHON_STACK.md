# React / no-Python stack version manifest (P1-M6-02)

| component | image / path | notes |
|---|---|---|
| Product UI | `services/central/static/product` → `/app/` | Default portal + `csv` recipe (`OPENFDD_STATIC_PRODUCT_UI=1`) |
| API | `services/central` → `openfdd-central` | Timescale historian, SQL FDD, JWT REST |
| React rollback | `archive/product-ui/react-spa-v4` → `openfdd-web` | Optional `docker/compose.react.yml` |

Compose files: [`docker/compose.portal.yml`](../../docker/compose.portal.yml) · [`docker/compose.csv.yml`](../../docker/compose.csv.yml)

```bash
docker compose -f docker/compose.portal.yml -f docker/compose.timescale.yml config
# health: GET http://localhost:8080/api/health
# UI:     http://localhost:8080/app/
```

Rollback to React: add `-f docker/compose.react.yml` and pin `OPENFDD_WEB_IMAGE` — see [LOCAL_HOSTING.md](../../operations/LOCAL_HOSTING.md).
