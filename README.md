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

This repository is the **`open-fdd`** **rules engine**: YAML-defined fault detection on **pandas** `DataFrame`s (`open_fdd.engine`). The published **PyPI** wheel contains only the `open_fdd` package.

---

## Install from PyPI

```bash
pip install open-fdd
```

---

## Online Documentation

This application is part of a broader ecosystem that together forms the **Open FDD AFDD Stack**, enabling a fully orchestrated, edge-deployable analytics and optimization platform for building automation systems.

* 🔗 **DIY BACnet Server**
  Lightweight BACnet server with JSON-RPC and MQTT support for IoT integrations.
  [Documentation](https://bbartling.github.io/diy-bacnet-server/) · [GitHub](https://github.com/bbartling/diy-bacnet-server)

* 📖 **Open FDD AFDD Stack**
  Full AFDD framework with Docker bootstrap, API services, drivers, and React web UI.
  [Documentation](https://bbartling.github.io/open-fdd-afdd-stack/) · [GitHub](https://github.com/bbartling/open-fdd-afdd-stack)

* 📘 **Open FDD Fault Detection Engine**
  Core rules engine with `RuleRunner`, YAML-based fault logic, and pandas workflows.
  [Documentation](https://bbartling.github.io/open-fdd/) · [GitHub](https://github.com/bbartling/open-fdd) · [PyPI](https://pypi.org/project/open-fdd/)

* ⚙️ **easy-aso Framework**
  Lightweight framework for Automated Supervisory Optimization (ASO) algorithms at the IoT edge.
  [Documentation](https://bbartling.github.io/easy-aso/) · [GitHub](https://github.com/bbartling/easy-aso) · [PyPI](https://pypi.org/project/easy-aso/0.1.7/)


---

## Develop and test

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
pytest
```

---

## Dependencies

* Python 3.12+
* `pandas`
* `numpy`
* `pyyaml`
* `pydantic>=2.4,<3`
* `pip` + virtual environment tooling (`python3 -m venv`)

---

## License

MIT
