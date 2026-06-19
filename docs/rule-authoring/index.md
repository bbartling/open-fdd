---
title: Rule authoring
parent: Rule Cookbook
nav_order: 2
has_children: true
---

# Rule authoring

Production FDD on the edge uses **PyArrow tables** from the feather historian. Optional **DataFusion SQL** covers simple stateless rules. Both backends share confirmation settings and batch execution.

| Page | Purpose |
|------|---------|
| [**PyArrow & DataFusion SQL**]({{ "/rule-cookbook/dual-backend-rules/" | relative_url }}) | Tutorial + backend decision guide |
| [Arrow rule contract]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }}) | `apply_faults_arrow`, `ArrowRuleResult`, lint rules |
| [Data types & units]({{ "/rule-authoring/data-types-and-units/" | relative_url }}) | Columns, nulls, command 0–1, sensor profiles |
| [Rust readiness]({{ "/rule-authoring/rust-readiness/" | relative_url }}) | Portable rule checklist |

## Packaging

```bash
pip install open-fdd              # PyArrow runtime (required)
pip install 'open-fdd[datafusion]' # optional SQL backend
```

## YAML files in the repo

| Location | Role |
|----------|------|
| `open_fdd/faults/catalog/*.yaml` | Fault-code **metadata** (not executable) |
| `open_fdd/default_rules/**/*.yaml` | Starter **metadata** — implement as `rules_py` Arrow/SQL modules |
| `workspace/data/rules_py/*.py` | **Executable** production rules |

## Fault codes

Assign letter codes (`VAV-C`, `AHU-A`, …) from the [Fault codes]({{ "/fault-codes/" | relative_url }}) reference — not legacy numeric `VAV-03` strings.
