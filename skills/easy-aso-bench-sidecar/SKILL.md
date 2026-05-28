---
name: easy-aso-bench-sidecar
description: "Runs easy-aso supervisor as an optional HVAC optimization sidecar behind Caddy. Use for bench ASO experiments alongside FDD stacks."
---

# easy-aso bench sidecar

Clone `easy-aso` to `/opt/easy-aso`; supervisor on 18090; Caddy path `/api/easyaso/*`.

Helper: `scripts/easy_aso_bench_runner.py` for health preflight and writing a bench agent under `workspace/scratch/`.

See ansible `easyaso` role and [caddy-lan-ingress-auth](../caddy-lan-ingress-auth/SKILL.md).
