---
title: Edge ForwardHistorian → Central (auth cheat sheet)
parent: How-to guides
nav_order: 7
---

# Edge ForwardHistorian → Central (auth cheat sheet)

Use this when **Central** runs in **volttron-docker** (`volttron1`) and an **edge** device (native `~/volttron`) should **forward historian traffic** over VIP to Central — **SQL / aggregation on Central**, BACnet and drivers stay on the edge.

**Security:** never commit real **`vctl auth serverkey`** output or **`vctl auth publickey`** credentials. Rotate any key that was pasted into chat or tickets.

**Bootstrap helpers (repo root):**

```bash
./scripts/bootstrap.sh --print-forward-historian-cheatsheet
OFDD_FORWARD_CENTRAL_VIP='tcp://YOUR_CENTRAL_IP:22916' \
  OFDD_FORWARD_CONFIG_OUT="$HOME/volttron/configs/forward-to-central.json" \
  ./scripts/bootstrap.sh --write-forward-historian-config-template
```

Then edit the JSON: set **`destination-serverkey`** to the output of **`vctl auth serverkey`** on Central. Restrict file permissions on the edge (e.g. `chmod 600`).

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
```

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

- **`destination-vip`:** Central VIP reachable from the edge LAN, e.g. `tcp://192.168.204.16:22916` (VIP port is usually **22916**, not the HTTPS web port).
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
5. Confirm with **logs** and historian/SQL on Central as applicable.

---

## 4) “Central only for SQL” (agent hygiene)

Open-F-DD **does not** modify **`~/volttron-docker`**. To **avoid** BACnet / platform driver on Central, stop or omit those agents **inside** the container (tags depend on your install), or trim **`platform_config.yml`** per [volttron-docker](https://github.com/VOLTTRON/volttron-docker) before **`docker compose up`**.

Bootstrap can print hints:

```bash
./scripts/bootstrap.sh --print-volttron-central-sql-forward-poc
```

---

## See also

- [VOLTTRON Central and AFDD parity](volttron_central_and_parity) — compose vs `VOLTTRON_HOME` stubs  
- [Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)  
- [Open‑Claw integration](../openclaw_integration) §1f  
- Upstream: [volttron-docker README](https://github.com/VOLTTRON/volttron-docker), [VOLTTRON Central deployment](https://volttron.readthedocs.io/en/main/deploying-volttron/multi-platform/volttron-central-deployment.html)
