---
title: Rule Cookbook
nav_order: 4
has_children: true
---

# Rule Cookbook

Arrow-native fault rules for the Operator Bridge historian. Production rules live in `workspace/data/rules_py/` and run via `POST /api/rules/batch`.

## Start here

| Page | Content |
|------|---------|
| [**PyArrow & DataFusion SQL**]({{ "/rule-cookbook/dual-backend-rules/" | relative_url }}) | **Same-rule tutorial**, when to use each backend, parity testing |
| [Rule authoring]({{ "/rule-authoring/" | relative_url }}) | Contract, types, Rust readiness |
| [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }}) | `min_true_rows`, duration, poll interval |
| [Python recipes (Arrow)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) | Copy-paste `apply_faults_arrow` modules |
| [DataFusion SQL recipes]({{ "/rule-cookbook/datafusion-sql-recipes/" | relative_url }}) | SQL threshold & spread patterns |
| [GL36 & sensor patterns]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) | AHU/VAV/RTU fault-code mapping |
| [Windowing & debugging]({{ "/rule-cookbook/windowing-debugging/" | relative_url }}) | Lookback, nulls, test tips |
| [Central plants]({{ "/rule-cookbook/central-plants/" | relative_url }}) | CHW / CTW / boiler patterns |

## Rule Lab

Author and test in the dashboard **Rule Lab** tab (`/rule-lab`): lint, preview on historian window, compare PyArrow vs SQL masks.

API: [Appendix — REST API]({{ "/appendix/bridge_api/" | relative_url }}) (Rules & FDD, Rule Lab sections).
