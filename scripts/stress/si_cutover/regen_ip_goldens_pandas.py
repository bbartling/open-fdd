#!/usr/bin/env python3
"""Refresh ip golden pandas + P2 rows (Timescale SQL regen when OPENFDD_DATABASE_URL is set)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402

GOLDENS = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens"
FC_RULES = frozenset(
    tuple(f"FC{i}" for i in range(1, 16)) + ("FC13-SAT-HIGH",)
)


def _merge_daily_for_rules(
    existing: list[dict] | None,
    fresh: list[dict],
    rule_ids: frozenset[str],
) -> list[dict]:
    """Replace only ``rule_ids`` rows; keep other rules' committed daily rows intact."""
    keep = [r for r in existing or [] if str(r.get("rule_id") or "") not in rule_ids]
    return cfl._normalize_daily_rows(keep + fresh)


def refresh_pandas_side(golden: dict, metric: dict, rules_by_id: dict) -> None:
    building_id = str(golden.get("building_id"))
    etype = str(golden.get("equipment_type") or "")
    poll = float(golden.get("poll_seconds") or 300.0)
    frame, equipment_id = cfl.reload_dataset_frame(golden)
    ip_frame = cfl.prepare_ip_frame(
        frame, building_id=building_id, equipment_id=equipment_id, equipment_type=etype
    )
    fc_ip: list[dict] = []
    fc_si: list[dict] = []
    p2_pairs: list[dict] = []
    for rule_id, rule in sorted(rules_by_id.items()):
        if rule_id not in FC_RULES or not rule.get("pandas_function"):
            continue
        params_reg = cfl.rule_params_from_registry(rule)
        params_ip = cfl.convert_params_to_ip(rule, params_reg, metric)
        params_si = cfl.convert_params_to_si(rule, params_reg, metric)
        ip_daily = cfl.run_rule_daily_rows(
            rule,
            ip_frame,
            building_id=building_id,
            equipment_id=equipment_id,
            params=params_ip,
            poll_seconds=poll,
        )
        si_frame = cfl.frame_to_si(ip_frame, metric)
        si_daily = cfl.run_rule_daily_rows(
            rule,
            si_frame,
            building_id=building_id,
            equipment_id=equipment_id,
            params=params_si,
            poll_seconds=poll,
        )
        fc_ip.extend(ip_daily)
        for row in si_daily:
            if row.get("pair_status") == "computed" and row.get("utc_day"):
                fc_si.append(dict(row))
        si_by_key = {
            cfl.si_fault_key(r): r
            for r in si_daily
            if r.get("pair_status") == "computed" and r.get("utc_day")
        }
        for row in ip_daily:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            si_row = si_by_key.get(cfl.si_fault_key(row))
            fs = float(si_row.get("fault_seconds", 0.0) if si_row else 0.0)
            p2_pairs.append(
                {
                    "rule_id": rule_id,
                    "equipment_id": equipment_id,
                    "utc_day": str(row.get("utc_day")),
                    "sql_si_fault_seconds": fs,
                    "pandas_si_fault_seconds": fs if si_row else None,
                    "pandas_si_status": "missing_si_cell" if si_row is None else "computed",
                    "sql_si_status": "computed",
                }
            )
    golden["pandas_fdd_daily"] = _merge_daily_for_rules(
        golden.get("pandas_fdd_daily"), fc_ip, FC_RULES
    )
    golden["pandas_si_daily"] = _merge_daily_for_rules(
        golden.get("pandas_si_daily"), fc_si, FC_RULES
    )
    if p2_pairs:
        other = [
            p
            for p in golden.get("p2_si_pairs") or []
            if str(p.get("rule_id")) not in FC_RULES
        ]
        golden["p2_si_pairs"] = sorted(
            other + p2_pairs,
            key=lambda r: (
                str(r.get("rule_id")),
                str(r.get("utc_day")),
                str(r.get("equipment_id")),
            ),
        )
    for row in golden.get("sql_fdd_daily") or []:
        rid = str(row.get("rule_id") or "")
        if rid not in FC_RULES or row.get("pair_status") != "computed":
            continue
        match = next(
            (
                p
                for p in golden["pandas_fdd_daily"]
                if p.get("rule_id") == rid
                and p.get("utc_day") == row.get("utc_day")
                and p.get("equipment_id") == row.get("equipment_id")
                and p.get("pair_status") == "computed"
            ),
            None,
        )
        if match is not None:
            row["fault_seconds"] = match["fault_seconds"]


def main() -> int:
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    metric = uc.load_json(uc.METRIC_UNITS)
    rules = cfl.load_rule_registry()
    rules_by_id = {str(r["rule_id"]): r for r in cfl.pandas_rules(rules)}
    if url:
        from scripts.stress.si_cutover.ci_fixtures_lib import emit_all_goldens

        emit_all_goldens(GOLDENS, database_url=url)
        print(f"Emitted {len(list(GOLDENS.glob('*.json')))} goldens via Timescale")
        return 0
    for path in sorted(GOLDENS.glob("*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        refresh_pandas_side(golden, metric, rules_by_id)
        path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Refreshed pandas/P2 (offline): {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
