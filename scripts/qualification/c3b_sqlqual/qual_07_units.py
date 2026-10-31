"""SQL-QUAL-07 — unit commutation, writer readback, rejected declarations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from scripts.stress.si_cutover import parity_chain as pc  # noqa: E402

from tests.qualification.fc6_flow_boundary_reference import DESIGN_L_S  # noqa: E402


def _cells_from_stage(stage, check_id: str) -> QualCell:
    if stage.errors:
        return QualCell(
            check_id,
            "FAIL",
            comparisons=stage.comparisons,
            detail="; ".join(stage.errors[:8]),
        )
    if stage.comparisons <= 0:
        return QualCell(check_id, "FAIL", 0, "zero comparisons")
    return QualCell(check_id, "PASS", comparisons=stage.comparisons)


def run_offline(conn=None) -> list[QualCell]:
    del conn
    cells: list[QualCell] = []
    cells.append(_cells_from_stage(pc.verify_unit_vector_goldens(), "07_unit_vectors_roundtrip"))
    cells.append(_cells_from_stage(pc.verify_unit_scenarios(), "07_si_parity_unit_scenarios"))
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ci" / "check_unit_contract.py")],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        cells.append(QualCell("07_unit_contract_ci", "FAIL", 0, tail or "check_unit_contract failed"))
    else:
        cells.append(QualCell("07_unit_contract_ci", "PASS", comparisons=1))

    wrong = 5000.0 * uc.REJECTED_LPS_PER_CFM
    if abs(wrong - DESIGN_L_S) >= 1e-3:
        cells.append(
            QualCell(
                "07_fc6_flow_precision_boundary",
                "PASS",
                comparisons=2,
                detail=f"design={DESIGN_L_S} rejected_default={wrong}",
            )
        )
    else:
        cells.append(
            QualCell(
                "07_fc6_flow_precision_boundary",
                "FAIL",
                1,
                "rejected lps/cfm default too close to canonical design flow",
            )
        )

    metric = pc._metric_doc()
    try:
        uc.convert_to_canonical(metric, "absolute_temperature", 72.0, "degF")
        uc.convert_to_canonical(metric, "absolute_temperature", 22.0, "degC")
        cells.append(QualCell("07_no_magnitude_unit_inference", "PASS", comparisons=2))
    except ValueError as exc:
        cells.append(QualCell("07_no_magnitude_unit_inference", "FAIL", 0, str(exc)))

    try:
        uc.convert_to_canonical(metric, "absolute_temperature", 50.0, "not_a_unit")
        cells.append(QualCell("07_reject_unknown_unit_alias", "FAIL", 0, "expected ValueError"))
    except ValueError:
        cells.append(QualCell("07_reject_unknown_unit_alias", "PASS", comparisons=1))

    cells.append(
        QualCell(
            "07_writer_api_final_cutover",
            "PENDING",
            0,
            "C5: live writer/API readback after SI cutover on owner stack",
        )
    )
    return cells


def run_postgres(conn) -> list[QualCell]:
    import pandas as pd

    from scripts.stress.si_cutover import ci_timescale_sql as cts

    cells: list[QualCell] = []
    site = "C3B_QUAL07_WRITER"
    equip = "EQUIP_QUAL07"
    idx = pd.date_range("2026-04-01T12:00:00Z", periods=3, freq="5min", tz="UTC")
    si_frame = pd.DataFrame(
        {
            "outside-air-temp": [21.0, 22.0, 23.0],
            "fan-status": [1.0, 1.0, 0.0],
        },
        index=idx,
    )
    parity = cts._load_parity_module()
    cur = conn.cursor()
    try:
        cts.purge_site(cur, site)
        conn.commit()
        cts.seed_frame(
            cur,
            parity,
            site_id=site,
            equipment_id=equip,
            equip_type="ahu",
            frame=si_frame,
            storage="si",
        )
        conn.commit()
        cur.execute(
            """
            SELECT val FROM sample
            WHERE site_id = %s AND openfdd_key = %s
            ORDER BY ts
            """,
            (site, f"{equip}.oa_t"),
        )
        vals = [float(r[0]) for r in cur.fetchall()]
        expected = [21.0, 22.0, 23.0]
        comparisons = len(expected)
        if vals == expected:
            cells.append(QualCell("07_pg_seed_readback_values", "PASS", comparisons=comparisons))
        else:
            cells.append(
                QualCell(
                    "07_pg_seed_readback_values",
                    "FAIL",
                    comparisons=comparisons,
                    detail=f"stored={vals} expected={expected}",
                )
            )
        cur.execute(
            """
            SELECT unit FROM point_map
            WHERE site_id = %s AND equipment_id = %s AND role = 'oa_t'
            LIMIT 1
            """,
            (site, equip),
        )
        row = cur.fetchone()
        unit = str(row[0]) if row else ""
        if unit == "degC":
            cells.append(QualCell("07_pg_point_map_declared_unit", "PASS", comparisons=1))
        else:
            cells.append(
                QualCell(
                    "07_pg_point_map_declared_unit",
                    "FAIL",
                    1,
                    f"unit={unit!r}",
                )
            )
    finally:
        cur.close()
        conn.rollback()
    return cells
