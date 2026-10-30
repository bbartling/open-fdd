#!/usr/bin/env python3
"""Refresh a W4 family's ip golden pandas + P2 rows (Timescale SQL when OPENFDD_DATABASE_URL is set).

Usage: regen_ip_goldens_w4c.py [--family W4c_si_zone|W4a_si_ahu_fc]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402
from scripts.stress.si_cutover.si_parity_families import (  # noqa: E402
    W4C_SI_ZONE_FAMILY,
    family_dataset_ids,
    family_rule_ids,
)

GOLDENS = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens"


def _merge_daily_for_rules(
    existing: list[dict] | None,
    fresh: list[dict],
    rule_ids: frozenset[str],
) -> list[dict]:
    """Replace only ``rule_ids`` rows; keep every other committed row intact."""
    keep = [r for r in existing or [] if str(r.get("rule_id") or "") not in rule_ids]
    mine = [r for r in fresh if str(r.get("rule_id") or "") in rule_ids]
    return cfl._normalize_daily_rows(keep + mine)


def refresh_pandas_side(golden: dict, metric: dict, rules_by_id: dict, family_rules: frozenset[str]) -> None:
    building_id = str(golden.get("building_id"))
    etype = str(golden.get("equipment_type") or "")
    poll = float(golden.get("poll_seconds") or 300.0)
    frame, equipment_id = cfl.reload_dataset_frame(golden)
    ip_frame = cfl.prepare_ip_frame(
        frame, building_id=building_id, equipment_id=equipment_id, equipment_type=etype
    )
    fam_ip: list[dict] = []
    fam_si: list[dict] = []
    p2_updates: list[dict] = []
    # Rules without a pandas function keep their committed rows (not recomputed here).
    refreshed = frozenset(
        rid for rid, rule in rules_by_id.items() if rid in family_rules and rule.get("pandas_function")
    )
    for rule_id, rule in sorted(rules_by_id.items()):
        if rule_id not in refreshed:
            continue
        params_ip, params_si = cfl.resolve_rule_params_ip_si(rule, metric)
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
        fam_ip.extend(ip_daily)
        for row in si_daily:
            if row.get("pair_status") == "computed" and row.get("utc_day"):
                fam_si.append(dict(row))
        si_by_key = {
            cfl.si_fault_key(r): r
            for r in si_daily
            if r.get("pair_status") == "computed" and r.get("utc_day")
        }
        for row in ip_daily:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            si_row = si_by_key.get(cfl.si_fault_key(row))
            p2_updates.append(
                cts.p2_pair_for_si_row(
                    rule_id=rule_id,
                    equipment_id=equipment_id,
                    utc_day=str(row.get("utc_day")),
                    pandas_si_fault_seconds=float(
                        si_row.get("fault_seconds", 0.0) if si_row else 0.0
                    ),
                    pandas_si_missing=si_row is None,
                    sql_si_fault_seconds=None,
                )
            )

    golden["pandas_fdd_daily"] = _merge_daily_for_rules(
        golden.get("pandas_fdd_daily"), fam_ip, refreshed
    )
    golden["pandas_si_daily"] = _merge_daily_for_rules(
        golden.get("pandas_si_daily"), fam_si, refreshed
    )
    existing_p2 = golden.get("p2_si_pairs") or []
    keep_p2 = [r for r in existing_p2 if str(r.get("rule_id") or "") not in refreshed]
    golden["p2_si_pairs"] = sorted(
        keep_p2 + p2_updates,
        key=lambda r: (str(r.get("rule_id")), str(r.get("utc_day")), str(r.get("equipment_id"))),
    )


def refresh_sql_side(golden: dict, metric: dict, rules_by_id: dict, conn, family_rules: frozenset[str]) -> None:
    from scripts.stress.si_cutover.ci_fixtures_lib import iter_dataset_specs, pandas_rules

    building_id = str(golden.get("building_id"))
    spec = next(s for s in iter_dataset_specs() if s.building_id == building_id)
    prules = pandas_rules(list(rules_by_id.values()))
    fresh = cfl.build_golden_for_dataset(spec, prules, metric, conn)
    golden["sql_fdd_daily"] = _merge_daily_for_rules(
        golden.get("sql_fdd_daily"), fresh.get("sql_fdd_daily") or [], family_rules
    )
    fresh_p2 = [r for r in fresh.get("p2_si_pairs") or [] if str(r.get("rule_id") or "") in family_rules]
    keep_p2 = [r for r in golden.get("p2_si_pairs") or [] if str(r.get("rule_id") or "") not in family_rules]
    golden["p2_si_pairs"] = sorted(
        keep_p2 + fresh_p2,
        key=lambda r: (str(r.get("rule_id")), str(r.get("utc_day")), str(r.get("equipment_id"))),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--family", default=W4C_SI_ZONE_FAMILY)
    args = ap.parse_args(argv)
    family_rules = family_rule_ids(args.family)
    metric = uc.load_json(uc.METRIC_UNITS)
    rules = cfl.load_rule_registry()
    rules_by_id = {str(r["rule_id"]): r for r in rules}
    db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    conn = None
    if db_url:
        from scripts.stress.si_cutover.ci_timescale_sql import _load_parity_module

        conn = _load_parity_module().connect_with_retry(db_url)
    for name in sorted(family_dataset_ids(args.family)):
        path = GOLDENS / f"{name}.json"
        golden = json.loads(path.read_text(encoding="utf-8"))
        refresh_pandas_side(golden, metric, rules_by_id, family_rules)
        if conn is not None:
            refresh_sql_side(golden, metric, rules_by_id, conn, family_rules)
        path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"updated {path.name}")
    if conn is not None:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
