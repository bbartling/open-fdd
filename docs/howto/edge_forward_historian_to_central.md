---
title: Edge ForwardHistorian → Central (auth cheat sheet)
parent: How-to guides
nav_order: 7
---

# Edge ForwardHistorian → Central (auth cheat sheet)

Use this when **Central** runs in **volttron-docker** (`volttron1`) and an **edge** device (native `~/volttron`) should **forward historian traffic** over VIP to Central — **SQL / aggregation on Central**, BACnet and drivers stay on the edge.

**Security:** never commit real **`vctl auth serverkey`** output or **`vctl auth publickey`** credentials. Rotate any key that was pasted into chat or tickets.

## Quick two-host runbook (copy-paste)

Use **two terminals**: one SSH’d to **Central** (Open-FDD + Docker), one to **edge** (e.g. bosspi). Do steps **in order**.

### A — Central only (hvac-edge-01, repo + Docker)

```bash
# 1) Repo root (folder must contain ./scripts/bootstrap.sh — see §0 for clone-name typos)
REPO_ROOT="${REPO_ROOT:-$HOME/open-fdd}"
cd "$REPO_ROOT"
test -f ./scripts/bootstrap.sh || { echo "Fix REPO_ROOT"; exit 1; }

# 2) Print this machine’s LAN IP — you will paste it on the edge as CENTRAL_IP
echo "CENTRAL_IP=$(hostname -I | awk '{print $1}')"

# 3) Is ZMQ VIP port open on the host? (expect a line with :22916 once volttron1 is up)
sudo ss -lntp | grep 22916 || echo "[WARN] nothing listening on 22916 yet — start/publish volttron-docker (see §0)"

# 4) Container / port mapping (expect 22916 published, e.g. 0.0.0.0:22916->22916/tcp)
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep -E 'volttron|22916|NAME' || true
./scripts/volttron-docker.sh ps 2>/dev/null || true

# 5) Server key for the edge ForwardHistorian JSON (destination-serverkey)
./scripts/bootstrap.sh --volttron-docker-serverkey

# 6) After edge gives you its forwarder public key (step E4 below):
# OFDD_VOLTTRON_AUTH_CREDENTIALS='<paste pubkey>' ./scripts/bootstrap.sh --volttron-docker-auth-add

# 7) DB + “did rows land?” heuristic (compose-db can be skipped if Timescale already up)
./scripts/bootstrap.sh --compose-db
./scripts/bootstrap.sh --volttron-docker-forward-proof
```

### B — Edge only (bosspi, native VOLTTRON)

```bash
# 1) Paste the IP from Central step A2 (example shows form only — use the real value)
CENTRAL_IP='192.168.204.16'   # <-- replace with output of: hostname -I | awk '{print $1}' on Central

# 2) This must succeed before the forwarder can work
nc -vz "$CENTRAL_IP" 22916

# 3) VOLTTRON shell
cd ~/volttron
source env/bin/activate
export VOLTTRON_HOME="${VOLTTRON_HOME:-$HOME/.volttron}"

# 4) Forwarder public key — paste into Central step A6
vctl auth publickey --tag forward-to-central

# 5) After Central runs auth-add, restart forwarder
vctl restart --tag forward-to-central
vctl status
```

### C — Order (minimal)

1. **Central:** **`ss` / `docker ps`** show **22916**; **`nc -vz CENTRAL_IP 22916`** from edge **succeeds**.  
2. **Central:** **`--volttron-docker-serverkey`** → put value in edge **`forward-to-central.json`** as **`destination-serverkey`**; set **`destination-vip`** to **`tcp://CENTRAL_IP:22916`**.  
3. **Edge:** forwarder **running** → **`vctl auth publickey --tag forward-to-central`**.  
4. **Central:** **`--volttron-docker-auth-add`** with that pubkey.  
5. **Edge:** **`vctl restart --tag forward-to-central`**.  
6. **Central:** **`--volttron-docker-forward-proof`**.

---

## 0) Central host: repo root (`cd` typos) and ZMQ reachability

All **`./scripts/bootstrap.sh …`** commands must run from the **Open-FDD monorepo root** (the directory that contains **`./scripts/bootstrap.sh`**).

- A default clone uses the same spelling as the GitHub repo slug (one hyphen between **`open`** and **`fdd`**):

  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```

- A frequent typo inserts **another** hyphen between **`f`** and **`dd`** in the directory name. That path **does not exist**; Bash prints **`No such file or directory`**, and **`./scripts/bootstrap.sh`** is not found if you stay in the wrong directory.

**Sanity check (run on Central before copy‑pasting blocks):**

```bash
REPO_ROOT="${REPO_ROOT:-$HOME/open-fdd}"
cd "$REPO_ROOT"
test -f ./scripts/bootstrap.sh && echo "OK: repo root" || echo "FAIL: wrong REPO_ROOT or typo in directory name"
```

Set **`REPO_ROOT`** to your real clone if it is not **`$HOME/open-fdd`**.

**Edge → Central TCP gate:** in **`destination-vip`**, use the **LAN IP (or DNS)** of the host where **`volttron1`** publishes **ZMQ port 22916**. On the **edge**, verify **before** debugging serverkey/auth (set **`CENTRAL_IP`** to the value you printed on Central, e.g. **`192.168.204.16`**):

```bash
# on edge only:
CENTRAL_IP='192.168.204.16'   # replace with Central’s LAN IP
nc -vz "$CENTRAL_IP" 22916
```

**`Connection refused`** means nothing is accepting **TCP 22916** on that address (wrong IP, compose not publishing **22916**, or **`vip-address`** not bound for LAN access). Fix that first.

**Clone / update upstream compose checkout, then start containers** (per [volttron-docker](https://github.com/VOLTTRON/volttron-docker) README — image build and **`docker compose up -d`** live under **`OFDD_VOLTTRON_DOCKER_DIR`**, default **`$HOME/volttron-docker`**):

```bash
cd "$REPO_ROOT"
./scripts/bootstrap.sh --volttron-docker
cd "${OFDD_VOLTTRON_DOCKER_DIR:-$HOME/volttron-docker}"
# build image and: docker compose up -d  (see volttron-docker README)
cd "$REPO_ROOT" && ./scripts/volttron-docker.sh up -d
```

**Bootstrap helpers (from `$REPO_ROOT`):**

```bash
cd "$REPO_ROOT"
./scripts/bootstrap.sh --print-forward-historian-cheatsheet
CENTRAL_IP="$(hostname -I | awk '{print $1}')"
OFDD_FORWARD_CENTRAL_VIP="tcp://${CENTRAL_IP}:22916" \
  OFDD_FORWARD_CONFIG_OUT="$HOME/volttron/configs/forward-to-central.json" \
  ./scripts/bootstrap.sh --write-forward-historian-config-template
```

Then edit the JSON: set **`destination-serverkey`** to the output of **`vctl auth serverkey`** on Central. Restrict file permissions on the edge (e.g. `chmod 600`).

**Central “easy buttons” (same machine as the repo; replaces most `docker exec` / `vctl` typing):**

```bash
cd "$REPO_ROOT"
./scripts/bootstrap.sh --print-forward-historian-cheatsheet
./scripts/bootstrap.sh --compose-db
./scripts/bootstrap.sh --volttron-docker-serverkey
./scripts/bootstrap.sh --volttron-docker-cat-config
OFDD_VOLTTRON_AUTH_CREDENTIALS='<edge_forwarder_pubkey>' ./scripts/bootstrap.sh --volttron-docker-auth-add
./scripts/bootstrap.sh --volttron-docker-agents
./scripts/bootstrap.sh --volttron-docker-agent-status
./scripts/bootstrap.sh --volttron-docker-tail-logs
./scripts/bootstrap.sh --volttron-docker-forward-proof
```

- **`--volttron-docker-tail-logs`** — Tries **`$VOLTTRON_HOME/volttron.log`** (and **`logs/volttron.log`**) inside the container; many **`volttron-docker`** / **`eclipsevolttron`** runs **do not** create that file. In **`auto`** mode (default), the script **falls back to `docker logs`** on the **`volttron1`** container. Force with **`OFDD_VOLTTRON_LOG_SOURCE=docker`** or **`file`**.
- **`--volttron-docker-forward-proof`** — **Heuristic “did anything land?”** check: filtered **`docker logs`** plus **`SELECT`** counts on **`public.data`** in the **`openfdd`** database when the SQLHistorian uses the default table layout. It does **not** prove a specific BACnet object on the Pi mapped to a given **`topic_id`**; use edge logs, BACnet scrape config, and topic naming for that.

---

## Roles

| Host | Role |
|------|------|
| **Central** | Docker `volttron1`, ZMQ VIP on **22916** (typical), HTTPS web on **8443** (typical). You add the **edge forwarder’s public key** to Central auth. |
| **Edge** (e.g. Pi) | Native VOLTTRON, **ForwardHistorian** agent pointing at Central’s **VIP + serverkey**. |

---

## 1) Central (inside Docker)

```bash
docker exec -itu volttron volttron1 bash
```

**Central platform server key** (edge needs this in JSON):

```bash
vctl auth serverkey
```

**Inspect platform config:**

```bash
grep -E '^(vip-address|bind-web-address|volttron-central-address|instance-name|message-bus)=' "$VOLTTRON_HOME/config" || sed -n '1,80p' "$VOLTTRON_HOME/config"
```

**Register the edge forwarder’s public key** (after you obtain it from the edge in §2):

```bash
vctl auth add --credentials '<PASTE_EDGE_FORWARDER_PUBLICKEY>'
```

One-liners without an interactive shell:

```bash
docker exec --user volttron -it volttron1 vctl auth serverkey
docker exec --user volttron -it volttron1 sh -lc 'grep -E vip-address "$VOLTTRON_HOME/config"'
docker exec --user volttron -it volttron1 vctl auth add --credentials '<PASTE_EDGE_FORWARDER_PUBLICKEY>'
```

**Logs on Central** (examples):

```bash
docker exec --user volttron volttron1 sh -lc 'tail -n 120 "$VOLTTRON_HOME/volttron.log"'
docker exec --user volttron volttron1 sh -lc 'grep -iE "forward|vip|auth|error" "$VOLTTRON_HOME/volttron.log" | tail -n 60'
docker logs --tail 120 volttron1
```

If **`volttron.log`** is missing in the container, prefer **`docker logs`** or **`cd "$REPO_ROOT" && ./scripts/bootstrap.sh --volttron-docker-tail-logs`** (auto fallback).

Container name override: **`OFDD_VOLTTRON_DOCKER_SERVICE`** (default **`volttron1`**).

---

## 2) Edge (native install)

```bash
cd ~/volttron
source env/bin/activate
export VOLTTRON_HOME="${VOLTTRON_HOME:-$HOME/.volttron}"
mkdir -p configs
```

**Forwarder JSON** (`configs/forward-to-central.json`):

- **`destination-vip`:** Central VIP reachable from the edge LAN, e.g. `tcp://CENTRAL_LAN_IP:22916` (VIP port is usually **22916**, not the HTTPS web port). From the edge, **`nc -vz CENTRAL_LAN_IP 22916`** must succeed before you chase serverkey/auth.
- **`destination-serverkey`:** output of **`vctl auth serverkey`** on Central.
- **`capture_log_data`:** usually `false` unless you also forward log payloads.

Install and start (adjust `services/core/ForwardHistorian` path if your VOLTTRON tree differs):

```bash
vctl install --agent-config configs/forward-to-central.json services/core/ForwardHistorian --tag forward-to-central
vctl start --tag forward-to-central
vctl status
```

**Edge forwarder public key** (paste into Central `vctl auth add`):

```bash
vctl auth publickey --tag forward-to-central
```

After Central has added the credential, restart the forwarder:

```bash
vctl stop --tag forward-to-central
vctl start --tag forward-to-central
vctl status
```

**Logs on edge:**

```bash
tail -n 120 "$VOLTTRON_HOME/volttron.log"
grep -iE "forward|vip|auth|error" "$VOLTTRON_HOME/volttron.log" | tail -n 60
```

---

## 3) Order of operations (minimal)

1. Central **up** → **`vctl auth serverkey`**.  
2. Edge: JSON → **`vctl install` / `start`** forwarder → **`vctl auth publickey --tag forward-to-central`**.  
3. Central: **`vctl auth add --credentials …`**.  
4. Edge: **restart** forwarder.  
5. Confirm with **logs**, **`vctl status`**, and historian/SQL on Central as applicable. On the Open-FDD host, **`./scripts/bootstrap.sh --volttron-docker-forward-proof`** gives a quick Central-side hint (docker log lines + **`public.data`** row counts when the historian uses that table).

---

## 4) “Central only for SQL” (agent hygiene)

Open-FDD **does not** modify **`~/volttron-docker`**. To **avoid** BACnet / platform driver on Central, stop or omit those agents **inside** the container (tags depend on your install), or trim **`platform_config.yml`** per [volttron-docker](https://github.com/VOLTTRON/volttron-docker) before **`docker compose up`**.

Bootstrap can print hints:

```bash
cd "$REPO_ROOT"
./scripts/bootstrap.sh --print-volttron-central-sql-forward-poc
```

---

## See also

- [VOLTTRON Central and AFDD parity](volttron_central_and_parity) — compose vs `VOLTTRON_HOME` stubs  
- [Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)  
- [Open‑Claw integration](../openclaw_integration) §1f  
- Upstream: [volttron-docker README](https://github.com/VOLTTRON/volttron-docker), [VOLTTRON Central deployment](https://volttron.readthedocs.io/en/main/deploying-volttron/multi-platform/volttron-central-deployment.html)
