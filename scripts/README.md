# `scripts/` — Open-FDD host entry points

All **Open-FDD** automation lives here and under **`afdd_stack/`**. The **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** checkout (default **`$HOME/volttron-docker`**) is an **upstream sibling**: clone it with **`./scripts/bootstrap.sh --volttron-docker`**, but **do not** add Open-FDD project files or commits inside that repository.

| Script | Purpose |
|--------|--------|
| **`bootstrap.sh`** | Delegates to **`afdd_stack/scripts/bootstrap.sh`** — doctor, `--central-lab`, Timescale, VOLTTRON_HOME stubs, clone/update **volttron-docker**, tests, UI build flags, etc. |
| **`volttron-docker.sh`** | Runs **`docker compose …`** inside **`OFDD_VOLTTRON_DOCKER_DIR`** so you never need to treat the PNNL tree as part of Open-FDD. Example: `./scripts/volttron-docker.sh up -d` |
| **`build_docs_pdf.py`** | Maintainer helper to build the engine PDF (pre-existing in this directory). |

Typical Central lab:

```bash
cd open-fdd
./scripts/bootstrap.sh --central-lab
./scripts/bootstrap.sh --print-volttron-central-sql-forward-poc   # Edge→Central ForwardHistorian + log hints
# OFDD_FORWARD_CONFIG_OUT=/path/forward.json OFDD_FORWARD_CENTRAL_VIP=tcp://CENTRAL:22916 ./scripts/bootstrap.sh --write-forward-historian-config-template
./scripts/volttron-docker.sh up -d
./scripts/volttron-docker.sh ps
```
