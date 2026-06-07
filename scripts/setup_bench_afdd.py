#!/usr/bin/env python3
"""Import bench BRICK model + cookbook FDD rules; validate lint/test/batch.

Uses the same paths as the LLM workflow:
  GET  /api/model/export  → bench_import_model.json template
  POST /api/model/import  → ModelService.import_json

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
from openfdd_bridge.data_loader import load_frame_for_run  # noqa: E402
from openfdd_bridge.rule_store import RuleStore  # noqa: E402
from openfdd_bridge.ttl_service import TtlService  # noqa: E402

DATA = REPO / "workspace" / "data"
MODEL_IMPORT = DATA / "bench_import_model.json"
RULES_PY = DATA / "rules_py"


def _read_rule_code(name: str) -> str:
    """Load rule source from workspace/data/rules_py."""
    return (RULES_PY / name).read_text(encoding="utf-8")


BENCH_RULES: list[dict] = [
    {
        "id": "bench-oa-t-flatline-1h",
        "name": "Bench OA-T flatline 1h",
        "fault_code": "VAV-C",
        "code_file": "bench_oa-t_flatline_1h.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1173"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "bench-oa-t-oob",
        "name": "Bench OA-T out of bounds",
        "fault_code": "VAV-C",
        "code_file": "bench_oa-t_out_of_bounds.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1173"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "bench-stat-zn-t-flatline-1h",
        "name": "Bench stat ZN-T flatline 1h",
        "fault_code": "VAV-C",
        "code_file": "bench_stat_zn-t_flatline_1h.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-10014"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "duct-t-flatline-1h",
        "name": "Duct-T flatline 1h",
        "fault_code": "DC-C",
        "code_file": "duct-t_flatline_1h.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1192"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "duct-t-spread-1h",
        "name": "Duct-T spread 1h",
        "fault_code": "DC-C",
        "code_file": "duct-t_spread_1h.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1192"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "bench-oa-h-flatline-1h",
        "name": "Bench humidity flatline 1h",
        "fault_code": "BLD-B",
        "code_file": "bench_humidity_flatline_1h.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1168"], "equipment_ids": [], "brick_types": []},
    },
    {
        "id": "bench-oa-h-oob",
        "name": "Bench humidity out of bounds",
        "fault_code": "BLD-B",
        "code_file": "bench_humidity_out_of_bounds.py",
        "config": {},
        "bindings": {"point_ids": ["5007-analog-input-1168"], "equipment_ids": [], "brick_types": []},
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
                "mode": "rule",
                "code": code,
                "fault_code": spec["fault_code"],
                "config": spec["config"],
                "bindings": spec["bindings"],
                "severity": "warning",
                "enabled": True,
            },
            saved_by="setup_bench_afdd",
        )
        saved.append(entry)
        print(f"Saved rule {entry['id']} → {entry.get('source_path')}")
    return saved


def test_rules_on_frame(model: dict) -> None:
    site_id = "demo"
    frame, origin = load_frame_for_run(site_id)
    print(f"Test frame: origin={origin} rows={len(frame)} cols={list(frame.columns)}")
    if frame is None or frame.empty:
        print("  skip (no historian frame)")
        return
    sample = frame.tail(min(len(frame), 500))
    table = pa.Table.from_pandas(sample, preserve_index=False)
    for spec in BENCH_RULES:
        code = _read_rule_code(spec["code_file"])
        try:
            result = run_arrow_rule(code, table, {}, rule_id=spec["id"])
        except Exception as exc:
            print(f"  {spec['id']}: ERROR {exc}")
            continue
        if result.errors:
            print(f"  {spec['id']}: ERROR {result.errors[0]}")
        else:
            print(f"  {spec['id']}: rows={result.row_count} flagged={result.true_count}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true", help="skip import/save; test existing rules")
    parser.add_argument("--batch", action="store_true", help="run batch after setup")
    args = parser.parse_args()

    if args.test_only:
        model = ModelService().load()
    else:
        model = import_model()
        save_rules()

    test_rules_on_frame(model)

    if args.batch or not args.test_only:
        summary = run_batch(lookback_hours=1, use_chunks=False, persist=True)
        print(
            f"Batch: rules={summary['rules_run']} runs={summary['site_runs']} "
            f"flagged={summary['flagged_runs']} errors={summary['error_runs']} "
            f"lookback={summary.get('lookback_hours')}h"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
