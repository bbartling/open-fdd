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

## 2. Next Step Run the AHU7 scripts

Continue to the **Bounds** and **Flatline** tutorials to run your first AHU fault checks on real data.

The `open-fdd` repository includes an [examples directory](https://github.com/bbartling/open-fdd/tree/master/examples) with various scripts. This tutorial covers two: `check_faults_ahu7_flatline.py` (stuck sensors) and `check_faults_ahu7_bounds.py` (out-of-range values). We start with the flatline script.

This image shows an example of an Air Handling Unit (AHU):
![AHU in the GitHub Pages](https://raw.githubusercontent.com/bbartling/open-fdd/master/examples/rtu7_snip.png)

To run the example, navigate to the root directory of the `open-fdd` repository, create and activate a virtual environment, and then execute the script.

---

**Next:** [Flat Line Sensor Tutorial]({{ "flat_line_sensor_tuntorial" | relative_url }})
