"""Shared FC1 postgres grid context (matches test_mode_delay_consolidation_1437)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402


def fc1_synth_postgres_context():
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    fc1 = rules["FC1"]
    metric = uc.load_json(uc.METRIC_UNITS)
    params_ip, _si = cfl.resolve_rule_params_ip_si(fc1, metric)
    synth_spec = next(s for s in cfl.iter_dataset_specs() if s.equipment_id == "AHU_CASE_FC1")
    synth_frame = cfl.prepare_ip_frame(
        synth_spec.source["frame"],
        building_id=synth_spec.building_id,
        equipment_id=synth_spec.equipment_id,
        equipment_type=synth_spec.equipment_type,
    )
    poll = cts.infer_poll_seconds(synth_frame.index)
    return fc1, synth_spec, synth_frame, dict(params_ip), float(poll)


def params_for_grid_case(base_ip: dict[str, float], case: dict[str, Any]) -> dict[str, float]:
    params = dict(base_ip)
    params["startup_delay_min"] = float(case["startup_delay_min"])
    mode = case.get("mode_delay_min")
    if mode is None:
        params.pop("mode_delay_min", None)
    else:
        params["mode_delay_min"] = float(mode)
    return params
