---
title: Getting Started
nav_order: 2
---


# Getting Started — AHU7 Tutorial

Jump right in and run basic sensor health checks (bounds + flatline) on AHU7 sample data using **open-fdd**.

This quick start walks you through cloning the repository, installing from source, and preparing your environment to run the tutorials.

---

## 1. Install

Clone the repository and change into the project directory.

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
```

Create and activate a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
```

Install **open-fdd** from source.
(A future v2 release will be available on PyPI.)

```bash
pip install -e ".[dev]"
```

- **`-e`** — Editable install: links to your source so code changes take effect immediately (no reinstall).
- **`.[dev]`** — Install from current dir (`.`) with the `dev` extras: pytest, black, pre-commit.

**Not included:** `.[dev]` does not install Brick (rdflib) or notebook support. For the Brick workflow and fault viz notebook, add:

```bash
pip install -e ".[dev,brick]"      # Brick TTL, validate, run_all_rules_brick
pip install -e ".[dev,brick,viz]"  # + matplotlib for fault viz notebook
pip install ipykernel               # For .ipynb in VS Code (lightweight)
```

## 2. Next Step Run the AHU7 scripts

Continue to the **Bounds** and **Flatline** tutorials to run your first AHU fault checks on real data.

The [examples directory](https://github.com/bbartling/open-fdd/tree/master/examples) contains the tutorial scripts. Download `data_ahu7.csv` and place it in `examples/` before running (see the examples README for the download link). This tutorial covers two: `check_faults_ahu7_flatline.py` (stuck sensors) and `check_faults_ahu7_bounds.py` (out-of-range values). We start with the flatline script.

This image shows an example of a Variable Air Volume Air Handling Unit (VAV AHU) which depicts the `ahu7` data we will be using in the tutorials:
![AHU in the GitHub Pages](https://raw.githubusercontent.com/bbartling/open-fdd/master/examples/rtu7_snip.png)

On the next page, we will run a fault rule against a CSV dataset pulled from the AHU7 BAS.

**Running the tutorial on your end:** You don't need to run from inside the repo. Clone the repo only to install from source (`pip install -e ".[dev]"`). Then create a folder on your desktop (e.g. `my_rules`) with your rules and data, and run the tutorial scripts from there. Future versions will be on PyPI — `pip install open-fdd` — so you won't need to clone at all.

Follow along in the tutorial to get familiar with the [examples directory](https://github.com/bbartling/open-fdd/tree/master/examples). See the examples README for how to obtain the practice dataset.

**Rule types vs expressions:** All rule types produce boolean (true/false) fault flags. Only the `expression` type lets you write custom logic; the others (`bounds`, `flatline`, `hunting`, `oa_fraction`, `erv_efficiency`) use built-in checks in the engine. The flatline and bounds tutorials use those built-in types.

---

**Next:** [Bounds Rule]({{ "bounds_rule" | relative_url }})
