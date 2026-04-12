# Open-FDD Central UI agent

Small **VOLTTRON** agent that registers static files so the React app can load next to **VOLTTRON Central** on the same platform web port.

## Build the UI for a sub-path

From the monorepo root:

```bash
VITE_BASE_PATH=/openfdd/ ./scripts/bootstrap.sh --build-openfdd-ui
```

Then open `https://<host>:<port>/openfdd/` after the agent is running (same origin as VOLTTRON Central’s UI). **Central UI URL** in upstream docs is typically **`https://<host>:<port>/vc/index.html`** (and often **`/admin/login.html`** for the admin bootstrap page)—a bare **`/vc/`** path may **404** depending on static routing; use **`/vc/index.html`** when probing with `curl`.

## Configure

1. Copy `agent-config.example.json` to `agent-config.json` and set `web_root` to the absolute path of `afdd_stack/frontend/dist`, **or** run `./scripts/bootstrap.sh --write-openfdd-ui-agent-config`.
2. With **volttron-docker**, install this package **inside** the platform container (adjust container name / user per your compose file), for example:

   ```bash
   docker exec -itu volttron volttron1 bash -lc 'pip install -e /path/to/open-fdd/afdd_stack/volttron_agents/openfdd_central_ui'
   ```

   Mount the Open-FDD repo into the container if you use a host path for `-e`.

3. Install/start the agent with **`vctl`** (exact flags depend on your VOLTTRON 9.x build). Typical pattern:

   ```bash
   vctl install --tag openfdd_ui --vip-identity openfdd.central.ui \
     --agent-config /path/to/agent-config.json \
     "$(python -c 'import openfddcentralui, pathlib; print(pathlib.Path(openfddcentralui.__file__).parent)')"
   vctl start --tag openfdd_ui
   ```

   If `vctl install` does not accept a directory, use your site’s documented `install-agent.py` / packaging flow and point the config file at `web_root`.

## Platform prerequisites

- Run **`vcfg`** once on the instance to enable the web server and install **VolttronCentral** + **VolttronCentralPlatform** (see [VOLTTRON Central deployment](https://volttron.readthedocs.io/en/main/deploying-volttron/multi-platform/volttron-central-deployment.html)).
- This agent only adds **`/openfdd/`**; Central remains under **`/vc/`** (entry page **`/vc/index.html`** per upstream).

## API base URL

The built SPA still calls the **Open-FDD FastAPI** host. Set **`VITE_API_TARGET`** at build time if the API is not same-origin, or put a reverse proxy in front of both.
