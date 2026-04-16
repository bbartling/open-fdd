---
title: Testing plan
parent: Operations
nav_order: 7
---

# Testing plan

Engine-focused testing for the **`open-fdd`** package.

---

## Continuous integration

On every PR and push to **`main`**, **`master`**, or **`develop`**:

1. Install **`pip install -e ".[dev]"`**
2. Build combined docs text (`python scripts/build_docs_pdf.py --no-pdf`) for consistency checks
3. Run **`pytest`** on `open_fdd/tests`
4. Dry-run **`python -m build`** + **`twine check`** for **`open-fdd`** and **`packages/openfdd-engine`**

---

## Local hygiene

- Add **pytest** cases for new rule types, edge cases in expressions, and column-map behavior.
- Keep **fixtures** small and deterministic under **`open_fdd/tests/fixtures/rules/`**.

---

## Optional benches

If you maintain a separate hardware or BACnet lab, keep its automation **outside** this repository and pass normalized **`DataFrame`s** into **`RuleRunner`** here.
