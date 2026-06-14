#!/usr/bin/env python3
"""Import bench BRICK model + four source-agnostic FDD rules; validate lint/test/batch.

Run from repo root:
  python3 scripts/setup_bench_afdd.py
  python3 scripts/setup_bench_afdd.py --test-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

import pyarrow as pa  # noqa: E402

from open_fdd.arrow_runtime.backend import run_arrow_rule  # noqa: E402

from openfdd_bridge.fdd_runner import run_batch  # noqa: E402
from openfdd_bridge.model_service import ModelService  # noqa: E402
from openfdd_bridge.playground import lint_python  # noqa: E402
from openfdd_bridge.data_loader import historian_columns_for_rule, load_frame_for_run  # noqa: E402
from openfdd_bridge.rule_store import RuleStore  # noqa: E402
from openfdd_bridge.ttl_service import TtlService  # noqa: E402

DATA = REPO / "workspace" / "data"
MODEL_IMPORT = DATA / "bench_dual_source_model.json"
RULES_PY = DATA / "rules_py"

TEMP_POINT_IDS = [
    "5007-analog-input-1173",
    "5007-analog-input-1192",
    "5007-analog-input-10014",
    "niagara-bench9065-f4c0862bb4",
    "niagara-bench9065-9fc449ad9c",
    "niagara-bench9065-fa1b48f7f0",
]

HUMIDITY_POINT_IDS = [
    "5007-analog-input-1168",
    "niagara-bench9065-954f1fe9a8",
]


def _read_rule_code(name: str) -> str:
    return (RULES_PY / name).read_text(encoding="utf-8")


BENCH_RULES: list[dict] = [
    {
        "id": "temp-out-of-bounds",
        "name": "Temperature out of bounds",
        "short_description": "Temperature reading is outside the configured range.",
        "code_file": "temp_out_of_bounds.py",
        "config": {"low": 40.0, "high": 110.0},
        "bindings": {"point_ids": TEMP_POINT_IDS, "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "temp-rate-of-change",
        "name": "Temperature rate of change",
        "short_description": "Temperature is changing faster than the last hour of data typically allows.",
        "code_file": "temp_rate_of_change.py",
        "config": {"roc_multiplier": 3.0, "roc_floor": 0.15},
        "bindings": {"point_ids": TEMP_POINT_IDS, "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "humidity-out-of-bounds",
        "name": "Humidity out of bounds",
        "short_description": "Humidity reading is outside the configured range.",
        "code_file": "humidity_out_of_bounds.py",
        "config": {"low": 15.0, "high": 75.0},
        "bindings": {"point_ids": HUMIDITY_POINT_IDS, "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "humidity-rate-of-change",
        "name": "Humidity rate of change",
        "short_description": "Humidity is changing faster than the last hour of data typically allows.",
        "code_file": "humidity_rate_of_change.py",
        "config": {"roc_multiplier": 3.0, "roc_floor": 1.0},
        "bindings": {"point_ids": HUMIDITY_POINT_IDS, "equipment_ids": [], "brick_types": []},
    },
]


def import_model() -> dict:
    payload = json.loads(MODEL_IMPORT.read_text(encoding="utf-8"))
    svc = ModelService()
    counts = svc.import_json(payload, replace=True)
    TtlService().sync()
    print(f"Imported model: {counts}")
    return payload


def save_rules(*, replace_all: bool = True) -> list[dict]:
    store = RuleStore()
    if replace_all:
        store._save({"version": 1, "rules": []})
    saved: list[dict] = []
    for spec in BENCH_RULES:
        code = _read_rule_code(spec["code_file"])
        lint = lint_python(code)
        if not lint["ok"]:
            raise SystemExit(f"Lint failed for {spec['id']}: {lint['issues']}")
        entry = store.upsert(
            {
                "id": spec["id"],
                "name": spec["name"],
                "short_description": spec["short_description"],
                "mode": "rule",
                "code": code,
                "config": spec["config"],
                "bindings": spec["bindings"],
                "severity": "warning",
                "enabled": True,
            },
            saved_by="setup_bench_afdd",
        )
        saved.append(entry)
        print(f"Saved rule: {spec['id']} ({len(spec['bindings']['point_ids'])} points)")
    return saved


def run_batch_once() -> dict:
    return run_batch(limit=1000, lookback_hours=1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    if not args.test_only:
        import_model()
        save_rules(replace_all=True)
    batch = run_batch_once()
    runs = batch.get("runs") or []
    flagged = sum(int(r.get("flagged") or 0) for r in runs if isinstance(r, dict))
    print(f"Batch complete: {len(runs)} runs, {flagged} flagged samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
