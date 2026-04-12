# `scripts/` — Open-FDD host entry points

All **Open-FDD** automation lives here and under **`afdd_stack/`**. The **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** checkout (default **`$HOME/volttron-docker`**) is an **upstream sibling**: clone it with **`./scripts/bootstrap.sh --volttron-docker`**, but **do not** add Open-FDD project files or commits inside that repository.

| Script | Purpose |
|--------|--------|
| **`bootstrap.sh`** | Delegates to **`afdd_stack/scripts/bootstrap.sh`** — doctor, **`--compose-db`**, **`--central-lab`**, **`--volttron-docker-lab-up`**, **`--volttron-docker-*`** (serverkey, auth-add, tail-logs, **forward-proof**, …), tests, UI build. **`./scripts/bootstrap.sh --help`**. |
| **`volttron-docker.sh`** | Runs **`docker compose …`** inside **`OFDD_VOLTTRON_DOCKER_DIR`** so you never need to treat the PNNL tree as part of Open-FDD. Example: `./scripts/volttron-docker.sh up -d` |
| **`build_docs_pdf.py`** | Maintainer helper to build the engine PDF (pre-existing in this directory). |

Typical Central lab:

```bash
cd open-fdd
./scripts/bootstrap.sh --central-lab
./scripts/bootstrap.sh --compose-db && LOCAL_USER_ID=$(id -u) ./scripts/bootstrap.sh --volttron-docker-lab-up
./scripts/bootstrap.sh --print-forward-historian-cheatsheet
# OFDD_FORWARD_CONFIG_OUT=/path/forward.json OFDD_FORWARD_CENTRAL_VIP=tcp://CENTRAL:22916 ./scripts/bootstrap.sh --write-forward-historian-config-template
./scripts/bootstrap.sh --volttron-docker-serverkey
./scripts/bootstrap.sh --volttron-docker-forward-proof
```

Alternate: **`./scripts/volttron-docker.sh up -d`** instead of **`--volttron-docker-lab-up`** if you manage **`~/volttron-docker`** by hand.
