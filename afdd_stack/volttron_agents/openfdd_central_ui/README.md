# Open-F-DD Central UI agent

Small **VOLTTRON** agent that registers static files so the React app can load next to **VOLTTRON Central** on the same platform web port.

## Build the UI for a sub-path

From the monorepo root:

```bash
VITE_BASE_PATH=/openfdd/ ./afdd_stack/scripts/bootstrap.sh --build-openfdd-ui
```

Then open `https://<host>:<port>/openfdd/` after the agent is running (same origin as `/vc/` for Central).

## Configure

1. Copy `agent-config.example.json` to `agent-config.json` and set `web_root` to the absolute path of `afdd_stack/frontend/dist`, **or** run `./afdd_stack/scripts/bootstrap.sh --write-openfdd-ui-agent-config`.
2. Activate the **VOLTTRON** venv and install this package in editable mode:

   ```bash
   source "$OFDD_VOLTTRON_DIR/env/bin/activate"
   pip install -e "$PATH_TO_OPEN_FDD/afdd_stack/volttron_agents/openfdd_central_ui"
   ```

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
- This agent only adds **`/openfdd/`**; Central remains at **`/vc/`** (default upstream paths).

## API base URL

The built SPA still calls the **Open-F-DD FastAPI** host. Set **`VITE_API_TARGET`** at build time if the API is not same-origin, or put a reverse proxy in front of both.
