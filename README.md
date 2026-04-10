# Open-FDD

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)
[![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-Beta-blue)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/open-fdd?label=PyPI&logo=pypi&logoColor=white&cacheSeconds=600)](https://pypi.org/project/open-fdd/)


<div align="center">

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

</div>

This **monorepo** holds:

- **`open_fdd/`** — the **PyPI rules engine** ([`open-fdd`](https://pypi.org/project/open-fdd/)), published from CI as the slim wheel/sdist (no stack code in the wheel).
- **`afdd_stack/`** — the full on-prem **AFDD Docker platform** (FastAPI, TimescaleDB, BACnet scrapers, React UI). Run **`./afdd_stack/scripts/bootstrap.sh`** from the repo root after cloning.

Containers install the engine from the copied `open_fdd` sources alongside `openfdd_stack` via `pip install ".[stack]"` at image build time.

---

## Install Package from PyPi

```bash
pip install open-fdd
```

Examples: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** — quick runs for **Brick / Haystack / DBO / 223P** ontologies.


---

## Documentation


### Engine (Standalone / PyPI)

* 🛠️ **[Open-FDD Engine Docs](https://bbartling.github.io/open-fdd/)**
  RuleRunner, YAML rules, examples, and engine-only workflows

* 📕 **[Engine PDF Docs](https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf)**
  Offline / Kindle-friendly version of the engine documentation

---

### Full AFDD stack (`afdd_stack/`)

* 📗 **Same repo** — [`afdd_stack/README.md`](afdd_stack/README.md), `afdd_stack/stack/docker-compose.yml`, `./afdd_stack/scripts/bootstrap.sh`
* 💻 **Docs** — [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/) (Jekyll site includes engine + platform guides in `docs/`)

### Bootstrap (from repo root)

The `--bacnet-address` value is the static bind for BACnet/IP on OT LANs. Bootstrap supports **dual-NIC** hosts: bind BACnet on the OT interface; another interface can use DHCP for internet.

**Standard HTTP (no TLS) and app login**

```bash
cd open-fdd

printf '%s' 'YourSecurePassword' | ./afdd_stack/scripts/bootstrap.sh \
  --bacnet-address 192.168.204.16/24:47808 \
  --bacnet-instance 12345 \
  --user ben \
  --password-stdin
```

**LAN / firewall / ports:** See [Getting started — Standard HTTP lab](https://bbartling.github.io/open-fdd/getting_started#standard-http-lab-remote-lan-access) (bearer keys in `afdd_stack/stack/.env`, ports **80** / **8880** / **8000**, **ufw** hints).

**Self-signed TLS (Caddy) and app login**

```bash
cd open-fdd

printf '%s' 'YourSecurePassword' | ./afdd_stack/scripts/bootstrap.sh \
  --bacnet-address 192.168.204.16/24:47808 \
  --bacnet-instance 12345 \
  --user ben \
  --password-stdin \
  --caddy-self-signed
```

**Bootstrap troubleshooting**

```bash
./afdd_stack/scripts/bootstrap.sh --doctor
```

### Validate the stack with `curl` (after containers are up)

**API on loopback (plain HTTP)** — Compose maps the API to `127.0.0.1:8000` by default:

```bash
curl -sS http://127.0.0.1:8000/health
# Expect HTTP 200 and JSON including "status":"ok"
```

**HTTP-only Caddy** (bootstrap **without** `--caddy-self-signed`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
# Expect 200 (or another success redirect to the UI)
```

**Self-signed HTTPS** (bootstrap **with** `--caddy-self-signed`): `:80` redirects to `https://`; use **`-k`** so `curl` accepts the dev cert:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
# Often 301 → https://127.0.0.1/

curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1/
# Expect 200 (HTML shell for the React app)
```

If you follow redirects from `http://` with `curl -L`, add **`-k`** (e.g. `curl -skL http://127.0.0.1/`) so the HTTPS hop does not fail on certificate verification.

---

## Dependencies

See [`pyproject.toml`](pyproject.toml). **Engine runtime:** pandas, NumPy, PyYAML, pydantic. **Contributors / CI:** `pip install -e ".[dev]"` installs **pytest**, **stack** dependencies (FastAPI, rdflib, …), and tooling. **`pip install open-fdd`** from PyPI stays engine-only. **Brick TTL → column_map** (rdflib / SPARQL) lives under **`afdd_stack/openfdd_stack/`**, not in the published wheel. For **matplotlib** (notebooks / `fault_viz`) or **python-docx** (Word reports), install those packages separately if you use those modules.

---

## Contributing

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv env && source env/bin/activate
pip install -U pip && pip install -e ".[dev]"
python -m pytest
```

See also: [TESTING.md](TESTING.md), [docs/contributing.md](docs/contributing.md), and the channel on the `open-fdd` Discord for **`#dev-chat`**.

---

## License

MIT
