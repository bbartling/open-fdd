# Reference rule YAML (test bench / cookbook)

These files are **reference copies** for documentation, the [test bench rule catalog](../../../docs/rules/test_bench_rule_catalog.md) (published under **Fault rules** on GitHub Pages), and optional lab uploads. They are **not** the default rules loaded by a fresh stack.

- **Production default:** [`stack/rules/`](../../../stack/rules/) (`sensor_bounds.yaml`, `sensor_flatline.yaml`) — see [Fault rules overview](../../../docs/rules/overview.md).
- **To use a reference rule:** upload it via the Faults UI or copy into your configured `rules_dir` after review.

Keeping this directory in-repo keeps the [expression rule cookbook](../../../docs/expression_rule_cookbook.md) and automation (e.g. [`openclaw/bench/e2e/`](../e2e/)) aligned with named examples on GitHub and in the published docs.
