# UI smoke verification

Confirms the default React edge UI loads without legacy tabs or routes.

## Run

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

Open `http://127.0.0.1:8080`

## Expected UI

- Left **Driver Tree**: BACnet, Modbus, JSON API, Haystack
- Main tabs: Dashboard, SQL FDD, Plots, Haystack, CDL, Wire Sheet (and FDD Wires / SQL Rules when that feature is merged)
- No **Rule Lab** tab
- No `/api/haystack/model` requests

## Static asset checks

```bash
curl -fsS http://127.0.0.1:8080/app.js | grep -q "REAL DEAL BACNET CSV BUILD"
! curl -fsS http://127.0.0.1:8080/app.js | grep -q "Rule Lab"
! curl -fsS http://127.0.0.1:8080/app.js | grep -q "/api/haystack/model"
```

## Auth UI (when auth parity is merged)

- Unauthenticated users see a **Sign in** form (username + password)
- No one-click role buttons or self-mint login
- Logout clears token and returns to login

See [auth-and-login.md](auth-and-login.md) for credential generation.
