# Local web app quickstart

Canonical path to a **login-ready** Open-FDD React application (Rust edge + JWT + static dashboard).

| Item | Value |
| --- | --- |
| Preferred start (Docker) | `./scripts/openfdd_auth_init.sh --show-secrets` then `./scripts/openfdd_local_up.sh` |
| Fallback start (no Docker) | `./scripts/openfdd_cargo_up.sh` |
| UI URL | http://127.0.0.1:8080 |
| Login path | http://127.0.0.1:8080/login |
| Health | `GET /api/health` |
| Version | `GET /api/health` → `version` / `image_tag` |
| Workspace | `workspace/` (override with `OPENFDD_WORKSPACE`) |
| Auth env | `workspace/auth.env.local` (gitignored) |
| Bootstrap passwords | `workspace/bootstrap_credentials.once.txt` (gitignored, mode 600) |
| Logs (Docker) | `workspace/logs/local-up.log` |
| Logs (cargo) | `workspace/logs/edge-dev.log` |
| Stop (Docker) | `docker compose -f docker-compose.local.yml stop openfdd-bridge` |
| Stop (cargo) | `kill "$(cat workspace/logs/edge-dev.pid)"` or `pkill -f open_fdd_edge_prototype` |
| Reset import data | `./scripts/openfdd_workspace_reset_default.sh` |
| **API + UI checks** | `./scripts/openfdd_webapp_check.sh` |

Do **not** use the root `docker compose up --build` path on RAM-constrained hosts — it compiles npm + Rust inside Docker and can OOM. Prefer `docker-compose.local.yml` via `openfdd_local_up.sh`.

### Smoke / error checks

With the edge running on http://127.0.0.1:8080:

```bash
./scripts/openfdd_webapp_check.sh              # login + API + SPA (+ vitest if installed)
./scripts/openfdd_api_check.sh                 # backend only (auth, routes, ZIP)
./scripts/openfdd_frontend_check.sh            # SPA shell + assets (+ vitest)
./scripts/openfdd_login_ui_smoke.sh            # all roles login
```

Failed responses are saved under `workspace/logs/api_check_*` and `workspace/logs/frontend_check_*`.

---

## 1. One-time bootstrap credentials

```bash
cd ~/open-fdd   # or your clone
./scripts/openfdd_auth_init.sh --show-secrets
```

This writes:

* `workspace/auth.env.local` — bcrypt hashes + `OFDD_AUTH_SECRET` (not login passwords)
* `workspace/bootstrap_credentials.once.txt` — plaintext passwords once

Save the passwords, then delete the handoff file:

```bash
rm workspace/bootstrap_credentials.once.txt
```

Roles: `operator`, `integrator`, `agent`, `admin`.

Rotate later:

```bash
./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart
```

---

## 2A. Start with Docker (Windows Docker Desktop / WSL / Linux)

Requires Docker Desktop with WSL integration (or a native Docker Engine).

```bash
./scripts/openfdd_local_up.sh
# first image build (optional, needs disk + OPENFDD_ALLOW_LOCAL_BUILD=1):
# OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_local_up.sh --build
```

Open http://127.0.0.1:8080 → **Sign in** → use a password from the bootstrap handoff.

Smoke:

```bash
./scripts/openfdd_login_ui_smoke.sh
curl -fsS http://127.0.0.1:8080/api/health | jq .
```

---

## 2B. Start without Docker (cargo edge)

When Docker is unavailable in WSL:

```bash
./scripts/openfdd_auth_init.sh --show-secrets   # if auth.env.local missing
./scripts/openfdd_cargo_up.sh                  # builds release if needed, serves frontend/
```

Same URL: http://127.0.0.1:8080

Optional hot-reload UI (API still on :8080):

```bash
./scripts/openfdd_ui_dev.sh
# Vite: http://127.0.0.1:5173  (proxies /api → :8080)
```

---

## 3. Browser login flow

```text
start edge
→ open http://127.0.0.1:8080/login
→ enter username + bootstrap password
→ JWT stored in the browser
→ application shell (Overview / Data Workbench / …)
→ refresh — session remains until JWT TTL (default 8h)
→ Sign out
```

Invalid password → `invalid credentials`. Protected APIs without a token → HTTP 401.

Do **not** paste bcrypt hashes from `auth.env.local` into the password field.

---

## 4. Platform notes

### Windows + Docker Desktop

1. Start Docker Desktop.
2. Enable **Settings → Resources → WSL integration** for your distro.
3. From PowerShell or WSL: run the Docker start path above.
4. Browse http://127.0.0.1:8080 from Windows.

### WSL 2 without Docker

Use `./scripts/openfdd_cargo_up.sh`. If `docker` prints that the engine pipe is missing, start Docker Desktop or stay on the cargo path.

### Linux

Docker Engine or cargo path both work. Bind is `0.0.0.0:8080` in containers; cargo script defaults to `127.0.0.1:8080` unless `OPENFDD_BIND_HOST` is set.

---

## 5. Production shape (same process)

```text
open_fdd_edge_prototype
  ├── REST API + JWT
  ├── DataFusion / Arrow workspace
  └── FRONTEND_DIR → compiled React (frontend/)
```

There is no separate Python/Streamlit app in the production image. Vibe19 remains an offline oracle only.

---

## 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `missing workspace/auth.env.local` | `./scripts/openfdd_auth_init.sh --show-secrets` |
| Login rejects after rotate | Recreate container / restart cargo edge so env reloads |
| SPA 200 but blank | Rebuild dashboard: `(cd workspace/dashboard && npm ci && npm run build)` |
| Port in use | Stop old edge / `docker compose -f docker-compose.local.yml stop` |
| Docker missing in WSL | Start Docker Desktop + WSL integration, or use `openfdd_cargo_up.sh` |
