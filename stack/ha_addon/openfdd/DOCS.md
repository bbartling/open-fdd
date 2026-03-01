# Open-FDD Home Assistant Add-on

This add-on lives under **stack/ha_addon/openfdd/** (with other Dockerfile-related assets). It runs the Open-FDD API inside Home Assistant so the [Open-FDD Integration](https://github.com/bbartling/open-fdd) (stack/ha_integration) can discover and control FDD locally. Version comes from the same source as the FastAPI app: **pyproject.toml**. When you build the addon with `./scripts/bootstrap.sh --ha-addon`, the script injects the current pyproject.toml version into config.yaml.

## Install

1. Add the Open-FDD add-on repository (or copy this add-on into your local add-ons).
2. Install the "Open-FDD" add-on.
3. Set **API key** (required for auth; the integration will use this).
4. Optionally set **BACnet server URL** if your BACnet gateway is on another host (e.g. `http://192.168.1.10:8080`).
5. Start the add-on.

## Discovery

- The integration can auto-discover Open-FDD at the Supervisor host on port 8000 (or the port you set).
- If discovery fails, add the integration manually and enter the URL (e.g. `http://homeassistant.local:8000`) and API key.

## API key

- Generate a random string (e.g. `openssl rand -hex 24`) and set it in add-on options.
- Use the same key in the HA integration and in Node-RED (Bearer token).

## Security

- The add-on runs on your LAN; it is not exposed to the internet unless you do so.
- Use a strong API key. All endpoints (except `/health` and `/app`) require `Authorization: Bearer <api_key>`.

## Smoke test

After starting the add-on:

```bash
curl -s http://localhost:8000/health
# {"status":"ok",...}

curl -s -H "Authorization: Bearer YOUR_API_KEY" http://localhost:8000/capabilities
# {"version":"...","features":{"websocket":true,...}}
```

WebSocket (with token in query):

```bash
# Use a WS client; connect to ws://localhost:8000/ws/events?token=YOUR_API_KEY
# Send: {"type":"subscribe","topics":["fault.*"]}
# Send: {"type":"ping"} -> expect {"type":"pong"}
```
