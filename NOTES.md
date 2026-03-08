# Notes (high-level, for maintainer only)

- **Git → PR → fetch prune:** See [Contributing — Git workflow](docs/contributing.md#git-workflow-branch--pr--sync): `git add .` → `git commit -m 'note'` → `git checkout -b feature/short-name` → `git push -u origin feature/short-name` → open PR → after merge: `git fetch --prune` → `git checkout main` (or `master`) → `git pull`.

- **Frontend hot reload:** Turn it off once the UI is solid enough and before Phase 1 (auth). Run the frontend as a production build (e.g. serve `frontend/dist` via Caddy or the API) so E2E and manual testing hit the same bundle you’ll deploy. The stack’s frontend container currently runs `npm run dev`; when you’re ready, switch it to build + serve static (or use Caddy to serve the built app) so there’s no HMR and behavior matches production.

---

## Security / auth – next steps (high level)

**Current:** Bearer token from `stack/.env` (`OFDD_API_KEY`). Bootstrap generates a key if missing (unless `--no-auth`). Frontend uses same key (e.g. `VITE_OFDD_API_KEY` at build or runtime) and sends `Authorization: Bearer <key>` and `?token=` on WebSocket. Single shared secret, no expiry, no user identity.

**Planned direction:**

1. **Bearer tokens should expire**
   - Common pattern: short-lived **access token** (e.g. 15–60 min) + **refresh token** (longer-lived, or session-based). Frontend stores both; when access token expires, call a refresh endpoint to get a new access token (and optionally new refresh token). Alternative: only access tokens, refresh endpoint accepts current valid token and returns a new one (rolling session).
   - JWT is common: access token is a signed JWT with `exp`; backend verifies signature and expiry. Refresh can be opaque (stored server-side) or another JWT with longer `exp`.
   - Frontend: on 401, try refresh once; if refresh fails, redirect to login. Use a single place (e.g. axios/fetch interceptor or API layer) so all requests and WebSocket get the current token.

2. **New FastAPI route(s) for refresh / token**
   - **POST /auth/refresh** (or similar): body = `{ "refresh_token": "..." }` (or cookie). Returns `{ "access_token": "...", "expires_in": 3600 }`. Optionally rotate refresh token (return new one, invalidate old).
   - **POST /auth/login** (see below) returns both access and refresh (or only access if no refresh flow).
   - Keep existing Bearer check for API and WebSocket; validate that the token is a valid access token (JWT or lookup) and not revoked.

3. **React login screen + backend “logged in” user**
   - Add a login page (e.g. `/login`). After successful login, store tokens (memory + optional httpOnly cookie or secure storage), then redirect to app. All API/WS use the access token.
   - Backend: “logged in” = valid access token (and optionally a user id in the token or DB). No need for full session store if using JWT; if using opaque tokens, store session server-side and tie to user.

4. **Bootstrap: one app user, username + password**
   - **Idea:** Bootstrap takes args for a single app user, e.g. `--user openfdd --password <pwd>`. That user is the only one who can log in. To change user/password, re-run bootstrap with new args (or a dedicated “change password” flow later).
   - **stack/.env:** Either (a) **no** long-lived API key in .env; bootstrap only stores the **hashed** password (see below) and optionally a seed used for signing JWTs. Or (b) keep one “bootstrap” or “machine” key in .env for non-browser clients (e.g. HA, scripts) and add a separate **user** login for the React app. Clarify which you want: single credential for everything vs. user login only for the UI.

5. **Hashed password – how to store and use (file, like Node-RED)**
   - **Never store plaintext.** Use a proper hash: **bcrypt** or **argon2** (e.g. `argon2-cffi`). Salt is included in the hash string.
   - **Store in a file only**, same idea as Node-RED credentials: no DB for the single app user. Bootstrap writes one file the backend reads at startup.
     - **Bootstrap:** When `--user` and `--password` are provided, run `hash = argon2.hash(password)` (or bcrypt). Write the hash (and optionally username) to a single file, e.g. `stack/.env` as `OFDD_APP_USER=openfdd` and `OFDD_APP_USER_HASH=argon2$...`, or a dedicated `stack/auth.env` / `config/auth.txt` with one or two lines (username, hash). Backend at startup reads this file and loads the single user + hash into memory for login checks.
     - No `users` table for now; keep it file-based. If you add multiple users later, you can introduce a DB then.
   - **Login flow:** Frontend POSTs `{ "username", "password" }` to **POST /auth/login**. Backend reads username + hash from the file, runs `argon2.verify(stored_hash, password)`; if OK, issue access (and optionally refresh) token. Return 401 on wrong password; don’t leak whether username exists.
   - **Security:** HTTPS in production; refresh token in httpOnly cookie if possible; short-lived access token; invalidate refresh tokens on logout / password change.

**Summary for implementation order:** (1) Add password hashing in bootstrap and store hash in a file (e.g. stack/.env or stack/auth.env), like Node-RED. (2) Add POST /auth/login (verify password, return JWT or opaque tokens). (3) Add POST /auth/refresh and make access tokens expire. (4) React: login page, store tokens, use them for API + WS, refresh on 401. (5) Decide whether to keep `OFDD_API_KEY` in .env for machine access or drop it in favor of user-only login.

---

## Phase 2 – security (stack, DB, Caddy)

**Frontend only talks to the backend.** React never hits the DB; all data goes through the API. Phase 2 is about tightening the stack and network so that stays true and traffic is protected.

1. **Database: no direct remote access (do it in the stack, not Caddy)**
   - Caddy is a reverse proxy for **HTTP/HTTPS** (API, frontend). It does **not** proxy Postgres port 5432. So “restrict DB” is done in the stack, not Caddy.
   - **Option A – don’t publish 5432:** In `docker-compose.yml`, remove `ports: - "5432:5432"` from the `db` service. Then only containers on the same Docker network (API, scrapers, Grafana, etc.) can reach `db:5432`. The host (and any remote client) cannot connect to the DB; all data access must go through the API. Downside: you can’t run `psql` or a GUI from the host unless you add a one-off “admin” container that has the DSN and publishes a port, or you `docker exec` into a container that has `psql`.
   - **Option B – keep 5432 but bind to host localhost only:** Publish `127.0.0.1:5432:5432` so only the host can connect to localhost:5432; no external IP. Remote clients still cannot reach the DB; use the API.
   - **Recommendation:** For “DB only via API,” use Option A (no publish) in production; use Option B or keep current publish only for local dev if you need host-side `psql`.

2. **Caddy: HTTPS and optional edge auth**
   - **TLS:** Use Caddy to terminate HTTPS (e.g. automatic certs or your own). All browser traffic to the app and API goes over HTTPS. API and frontend can stay HTTP behind Caddy (or use HTTPS internally if you prefer).
   - **Optional Caddy auth:** You can add Caddy auth (e.g. basicauth, or an auth plugin) in front of the app so that even before hitting the React app, users must pass Caddy’s check. That’s a second layer; the main auth (login, Bearer, refresh) stays in the app and API. Use Caddy auth if you want “lock the whole site behind a shared secret or LDAP” in front of the app’s own login.
   - **Headers / hardening:** Caddy can add security headers (HSTS, X-Frame-Options, etc.) and rate limiting. Document the chosen Caddy config in `docs/` or stack README.

3. **Secrets and .env**
   - Keep `stack/.env` out of version control; bootstrap (or deploy) generates/updates it. For Phase 2 auth, the hashed password (and optional JWT secret) live in that file or a dedicated auth file; never commit them.
   - If you need machine access (HA, scripts) alongside user login, keep a separate long-lived token or API key in .env and document that it’s for non-browser use only.

4. **Checklist for Phase 2**
   - [ ] DB: Remove `5432:5432` (or bind to `127.0.0.1:5432`) so DB is not remotely reachable; all access via API.
   - [ ] Caddy: Enable HTTPS; optionally add edge auth or security headers.
   - [ ] Implement Phase 1 auth (login, refresh, hashed password in file).
   - [ ] Ensure frontend and WebSocket only use the API (no DB connection); document that in README or security doc.

---

## Phase 3 – Trivy (security scanning during dev)

**Trivy** is a CLI security scanner: container images, filesystems, IaC (Dockerfile, Terraform), secrets, and dependency/SBOM. No server; run locally or in CI. Good fit for “scan the app during the dev process.”

**When to use Trivy:**

- **After building images** – Before pushing or deploying, scan your built images for known CVEs in OS packages and app dependencies. E.g. `trivy image openfdd-api:latest` (and same for frontend, scrapers, etc.). Fix by updating base image or bumping packages, then re-scan.
- **In CI / before merge** – Run Trivy in a pipeline (e.g. on every PR or on main): `trivy image ...`, and optionally `trivy fs .` or `trivy config .` so new code doesn’t introduce bad config or secrets.
- **When changing Dockerfiles or base images** – Scan the new image to see impact of a base upgrade or new layers. Helps decide “is this base image safe to use?”
- **Optional: filesystem / config / secrets** – `trivy fs .` scans the repo for vulnerabilities in lockfiles (e.g. package-lock.json, requirements.txt); `trivy config .` for Dockerfile/compose misconfigs; `trivy secret .` for accidentally committed secrets. Use when you add dependencies or change infra config.

**Practical dev workflow:** (1) Build image. (2) Run `trivy image <name>:<tag>`. (3) Triage: ignore accepted risks or fix (update base, bump deps). (4) Optionally add a `make trivy` or script so the team runs it before push. Phase 3 = “Trivy in the loop” so scanning is part of normal dev, not only production.

**Docs:** Full quickstart and when-to-use: **docs/howto/trivy.md**. Listed in [How-to Guides](docs/howto/index.md) and referenced from [Security](docs/security.md). **Keep docs up to date:** when you add/rename stack images or change Trivy/CI usage, update the Trivy howto, NOTES Phase 3, and any `trivy-scan` script so Phase 3 stays accurate.

---

## Platform config (RDF) and scrapers – what’s used, what can be cleaned up

**Where config lives:** `config/data_model.ttl` holds `ofdd:platform_config` (lines 7–24). The API loads this into the in-memory graph on startup; GET/PUT `/config` read/write that graph and serialize back to the TTL file. Effective config = overlay from graph (plus env `OFDD_*` as fallback). So the RDF block in `data_model.ttl` is the **source of truth** for the platform when the API is running.

**Open-Meteo scraper:**

- **Standalone** (`run_weather_fetch.py` or `run_weather_fetch.py --loop`): Fetches config via **GET /config** (so it sees the graph/RDF config). Uses `open_meteo_enabled`, `open_meteo_interval_hours`, `open_meteo_latitude`, `open_meteo_longitude`, `open_meteo_days_back`, `open_meteo_timezone`, `open_meteo_site_id`. The **interval** (`open_meteo_interval_hours`, e.g. 24 in the TTL) is only used here: it’s the sleep between fetches when you run `--loop`. So “fetch every 24 h” applies to the standalone weather scraper only.
- **FDD loop** (`run_rule_loop.py`): Does **not** use `open_meteo_interval_hours`. It fetches weather **once per FDD run** using `get_platform_settings()` (graph overlay). So weather is fetched every **rule_interval_hours** (e.g. 3), using **lookback_days** for the window. So when you use the FDD loop, the “24” in `ofdd:openMeteoIntervalHours` has no effect; only the standalone weather scraper respects it.

**FDD routine vs default config:**

- FDD loop uses: `rule_interval_hours`, `lookback_days`, `rules_dir`, and for weather (before each run): `open_meteo_enabled`, `open_meteo_site_id`, `open_meteo_latitude`, `open_meteo_longitude`, `open_meteo_timezone`, and **lookback_days** (not `open_meteo_days_back` — the FDD loop passes `lookback_days` to the weather fetch so the window matches the rule run). So in the RDF, **openMeteoDaysBack** is used by the standalone scraper and by the API/config display; the FDD loop itself uses **lookbackDays** for the weather window.
- All keys in the RDF block are still used somewhere (API GET/PUT, FDD loop, BACnet scraper, standalone weather scraper, or graph sync). Nothing in that block is dead.

**Cleanup / consistency done:**

- **bacnet_enabled:** The RDF and API use `bacnet_enabled`; `PlatformSettings` had `bacnet_scrape_enabled`. The overlay was never applied to the BACnet scraper because the attr name didn’t match. **Fixed:** `get_platform_settings()` now maps overlay key `bacnet_enabled` → attr `bacnet_scrape_enabled`, so changing “Enable BACnet” in the UI or via PUT `/config` correctly turns the scraper on/off.

**Optional doc cleanup:**

- In `run_weather_fetch.py` or the weather howto, add one sentence: “When using the FDD loop, weather is fetched every FDD run (every `rule_interval_hours`); `open_meteo_interval_hours` only applies to the standalone `run_weather_fetch.py --loop`.” So it’s clear that the 24 in the TTL is for the standalone scraper, not for the FDD-driven fetch.
