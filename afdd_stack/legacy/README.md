# Legacy notes

The **Docker Compose** file under **`afdd_stack/stack/docker-compose.yml`** now only starts:

- **`db`** — TimescaleDB/Postgres with **`openfdd`** database and **`stack/sql/*.sql`** on first init (fault schema, sites, points, etc.). Use the same host for a **VOLTTRON SQL historian** (or VOLTTRON Central’s DB) per [SQLHistorian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html) — table names can use `tables_def` if you must share one Postgres instance.
- **Optional profiles:** `grafana`, `mqtt` (`docker compose --profile grafana up -d`).

**Removed from Compose (by design):** diy-bacnet-server, BACnet scraper, FastAPI **api** container, **Caddy**, **frontend** container, FDD loop container, weather scraper, host-stats. Those roles move to **VOLTTRON agents** and **Central** UI/auth.

**Bootstrap:** **`./scripts/bootstrap.sh`** — optional **`--compose-db`**, **`--volttron-docker`** / **`--central-lab`**, then build/run **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** on the host (not a host venv of VOLTTRON inside this repo).
