# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)

![Fault Detection Visualization](https://raw.githubusercontent.com/bbartling/open-fdd/master/open_fdd/air_handling_unit/images/plot_for_repo.png)

## 🔥 What is open-fdd?
**open-fdd** is an **open-source Fault Detection and Diagnostics (FDD) tool** designed for analysts and engineers using local toolsets like Jupyter notebooks. It is not necessarily an IoT tool for **Grafana**, which an MSI (Master Systems Integrator) might use, though it could be adapted for that purpose. Instead, it is tailored for **individual engineers analyzing historical HVAC system data** using the **Pandas computing library**. While it could potentially be integrated with a database, doing so may require additional effort. It leverages **ASHRAE** and **NIST**-inspired fault equations. Built on Python and **Pandas**, this library enables efficient detection of operational issues in HVAC systems with:

This version improves clarity and flow while keeping it professional and readable. 🚀 Let me know if you want any more refinements!

✅ **Pre-built fault equations** for detecting HVAC anomalies
✅ **Seamless Pandas integration** for time-series analysis
✅ **Extensible architecture** for custom fault conditions
✅ **Open-source & community-driven** development


📖 **See Online Documentation:**  
[📚 Open-FDD Docs](https://bbartling.github.io/open-fdd/)

---

## 🚀 Getting Started
### Installation
Install `open-fdd` from PyPI with:
```bash
pip install open-fdd
```

### Quick Example
```python
import pandas as pd
from open_fdd.air_handling_unit.fault_condition_one import FaultConditionOne

# Sample data
data = {
    "timestamp": pd.date_range(start="2023-01-01", periods=10, freq="15T"),
    "supply_air_temp": [54, 55, 56, 57, 58, 59, 60, 61, 62, 63],
    "return_air_temp": [70, 70, 70, 70, 70, 70, 70, 70, 70, 70],
}
df = pd.DataFrame(data)

# Run fault detection
fault_checker = FaultConditionOne(df)
df_faults = fault_checker.process()
print(df_faults)
```

---

## 📌 Project Goals
`open-fdd` aims to provide a full-featured **Fault Detection & Diagnostics (FDD) platform** with:

### ✅ Completed Features
- [x] Air handling unit (AHU) fault conditions & reports (aligned with ASHRAE/NIST)
- [x] PyPI distribution for easy installation

### 🔄 In Progress
- [ ] Jupyter notebook tutorials showcasing AHU FDD examples + BRICK metadata integration
- [ ] Expansion to **central plant** fault conditions (chillers, boilers, pumps)
- [ ] Jupyter notebook tutorials showcasing AHU FDD examples + BRICK metadata integration

### ⏳ Upcoming
- [ ] **Energy Efficiency** fault detection & reporting
- [ ] **Metering** fault analytics & data modeling
- [ ] **SQL Integration** for storing results & visualizing in Grafana
- [ ] Dedicated documentation site (`github.io` or ReadTheDocs)

---

## 🤝 How to Contribute
We welcome contributions from the community! To get started:

1. **Clone the repository:**
```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
```
2. **Install dependencies:**
```bash
py -3.12 -m pip install -r requirements.txt
```
3. **Run tests:**
```bash
py -3.12 -m pytest
```
4. **Format with Black:**
```bash
py -3.12 -m black .
```
5. **Submit a Pull Request (PR)**

---

## 📜 License
`open-fdd` is released under the **MIT License**, ensuring it remains free and accessible for all.

```

【MIT License】

Copyright 2025 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
