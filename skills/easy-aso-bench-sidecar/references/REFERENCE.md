# easy-aso — reference

Ansible role `easyaso`; vars `easyaso_root`, `easyaso_supervisor_port`, `easyaso_state_dir`.

PyPI extra (retired monolith): `easy-aso[platform]`.

## Bench runner

```bash
python skills/easy-aso-bench-sidecar/scripts/easy_aso_bench_runner.py
```

Writes `workspace/scratch/easy_aso_bench_agent.py` by default. Promote stable helpers into this skill's `scripts/` via PR.
