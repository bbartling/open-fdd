---
title: PyPI agent tools
parent: Rules
nav_order: 7
---

# PyPI agent tools

[`open-fdd`](https://pypi.org/project/open-fdd/) on PyPI is the Python toolbox an AI agent (or an engineer) runs next
to the Open-FDD app. Everything is SI and read-only toward the building system. Package versions (4.x) are separate
from the app (5.x).

```bash
pip install open-fdd                       # core: ECM / ROI calculators and workbooks
pip install "open-fdd[nf,anomaly,ml]"      # add extras as needed (table below)
```

## Tools

| Tool | What it does | Extra | Example |
|---|---|---|---|
| Rules (`open_fdd.rules`) | pandas twins of the SQL fault rules, SI, same gates as the app | `oracle` | `from open_fdd.rules import run_all` |
| NF client (`open-fdd-nf`) | Read an NF box: model, roles, SI history, run the rules, summary report | `nf` | `open-fdd-nf rules --days 7` |
| SPARQL to DataFrame (`open-fdd-nf sparql`, `open_fdd.nf.sparql_data`) | SPARQL on the site model, matched points' history as SI DataFrames, then the rules | `nf` (`rdf` on Lite) | `open-fdd-nf sparql "SELECT ..." --days 7 --rows` |
| NF analytics (`open-fdd-nf analyze`) | Weekly runtime, cooling OAT bins, economizer, fault timeline, run on the box | `nf` | `open-fdd-nf analyze weekly-runtime --days 28` |
| Analytics (`open_fdd.analytics`) | Motor hours, OAT bins, VAV health, metering and degree days, M&V change point, weather and psychrometrics | `analytics` | `from open_fdd.analytics import motor_run_hours_table` |
| Anomaly screen (`open-fdd-anomaly screen`) | Rolling z-score, MAD, STL, Isolation Forest on a device folder, plots and scoreboard | `anomaly` | `open-fdd-anomaly screen ./AHU_1 --out ./out` |
| SQL z-score (`--engine sql`, `open_fdd.analytics.sql_anomaly`) | The z-score as portable SQL over `fdd.point` + `fdd.input_sample`; equals the pandas flags | `anomaly` (`duckdb`/`postgres` for those engines) | `open-fdd-anomaly screen ./AHU_1 --out ./out --methods zscore --engine sql` |
| RCx report (`open-fdd-anomaly report`) | Single-system or building FDD / RCx Typst report, PDF with `--compile` | `anomaly` | `open-fdd-anomaly report ./AHU_1 --out ./rpt --month 2026-06 --compile` |
| Engineering Findings (`open-fdd-report`) | Evidence-reviewed findings from a checklist, an NF box or a CSV: DOCX, XLSX, JSON | `reporting` | `open-fdd-report --csv export.csv --out ./findings --docx --xlsx` |
| ML detectors (`open-fdd-ml detect`) | PCA / SPE with contributions, gray-box residuals, mode-gated one-class SVM / COPOD, trained on known-good rows | `ml` (`ml-copod`) | `open-fdd-ml detect ./AHU_1 --method grey_box --train-until 2026-06-01 --out ./ml` |
| LBNL benchmark (`open-fdd-ml benchmark`) | Scores the rules and detectors on public LBNL AHU data: TPR, FPR, delay ([results](https://github.com/bbartling/open-fdd/blob/master/docs/ml/lbnl-ahu-benchmark.md)) | `ml` | `open-fdd-ml download && open-fdd-ml benchmark --out bench.md` |
| Device folder (`open-fdd-ml make-folder`) | Builds the `history_wide.csv` + `column_map.json` folder the anomaly and ML tools read, from any wide CSV (`--map ROLE=COLUMN`), an LBNL file or a synthetic example; `--list-roles` | `ml` | `open-fdd-ml make-folder trend.csv --time-col Time --map discharge-air-temp=SAT --map fan-status=SF_S --out AHU_1` |
| Method check (`open-fdd-ml methods`) | Roles each detector needs; with a folder, which can run and why not | `ml` | `open-fdd-ml methods ./AHU_1` |
| Ontology audit (`open-fdd-ontology-audit`) | Requirements sheet vs pinned Brick / 223P / Haystack snapshots (evidence-backed statuses); model doctor: standard vs Open-FDD vs site terms, identity, history links, SHACL | `ontology` (`ontology-shacl`) | `open-fdd-ontology-audit req.xlsx --graph building.ttl --shacl --out r` |
| Energy calcs (`open-fdd-ecm calc`) | Fan affinity, schedule reduction, OA sensible / total, economizer cap, CHW reset, kW/ton, boiler efficiency, condenser water | core | `open-fdd-ecm calc fan_affinity --json '{"design_kw":20,"hours":4000,"baseline_speed_fraction":1,"proposed_speed_fraction":0.8}'` |
| ROI (`open_fdd.ecm_engineering.finance`) | Simple payback and NPV with discount and escalation | core | `npv(50000, 12000, years=15, discount_rate=0.05)` |
| ECM workbooks (`open-fdd-ecm demo`, `stage2-workbook`) | Auditable Excel ECM workbooks with dual-rail inputs and assumptions | core | `open-fdd-ecm demo --out Demo_ECMs.xlsx` |
| EnergyPlus evidence (`open-fdd-ecm agent`) | Import EnergyPlus evidence; types `InputRail.ENERGYPLUS`, `SourceType.ENERGYPLUS_AUTOSIZED` / `_DERIVED`, provenance, honesty status (fitted vs ballpark) | core | `open-fdd-ecm agent import_energyplus_evidence evidence.json` |
| M&V (`ecm_engineering.changepoint`, `g14`) | IPMVP change-point baselines, ASHRAE Guideline 14 NMBE / CVRMSE | core | `from open_fdd.ecm_engineering import g14` |
| Parity (`open_fdd.parity`) | Seeded SI dataset and the pandas == SQL comparison | `oracle` | `python tests/parity/stress.py --engines duckdb` |
| Version (`open-fdd-version`) | Package and app versions as JSON | core | `open-fdd-version --pretty` |

Agent skills for these tools: [`openfdd_agent_spec/skills/`](https://github.com/bbartling/open-fdd/tree/master/openfdd_agent_spec/skills).
More detail: [python-tools.md](https://github.com/bbartling/open-fdd/blob/master/docs/python-tools.md).
The 4.x ECM guide (engineering calcs, IPMVP, EnergyPlus purpose) was retired from the site in 5.0 and is kept in
[git history](https://github.com/bbartling/open-fdd/tree/aa8dcfa0b3970b2fed066242072e784972cd6ab8/docs/ecm).
