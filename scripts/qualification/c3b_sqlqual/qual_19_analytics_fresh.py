"""All 19 analytics bodies — fresh PG SQL vs independent oracle (not golden-only)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from scripts.stress.si_cutover import analytics_parity as ap  # noqa: E402
from scripts.stress.si_cutover import ci_analytics_p2 as cap2  # noqa: E402
from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402


def _metric() -> dict[str, Any]:
    import json

    return json.loads((REPO / "sql" / "contract" / "metric_units.json").read_text(encoding="utf-8"))


def run_offline() -> list[QualCell]:
    stems = cap2.all_analytics_sql_stems()
    cells: list[QualCell] = []
    if len(stems) != 19:
        cells.append(
            QualCell(
                "19_analytics_body_count",
                "FAIL",
                0,
                f"expected 19 stems, found {len(stems)}",
            )
        )
    else:
        cells.append(QualCell("19_analytics_body_count", "PASS", comparisons=19))
    if "sql_anomaly_series" not in stems:
        cells.append(QualCell("19_sql_anomaly_series_present", "FAIL", 0, "stem missing"))
    else:
        cells.append(QualCell("19_sql_anomaly_series_present", "PASS", comparisons=1))
    registry_stems = {Path(p).stem for p in cap2.registry_sql_paths()}
    missing_registry = set(stems) - registry_stems
    if missing_registry:
        cells.append(
            QualCell(
                "19_registry_covers_shipped_sql",
                "FAIL",
                0,
                f"missing {sorted(missing_registry)}",
            )
        )
    else:
        cells.append(QualCell("19_registry_covers_shipped_sql", "PASS", comparisons=len(stems)))
    p1, p2 = ap.run_analytics_stages(scope=None)
    if p1.errors or p2.errors:
        detail = "\n".join(list(p1.errors[:3]) + list(p2.errors[:3]))
        cells.append(
            QualCell(
                "19_offline_pandas_stages",
                "FAIL",
                p1.comparisons + p2.comparisons,
                detail,
            )
        )
    else:
        cells.append(
            QualCell(
                "19_offline_pandas_stages",
                "PASS",
                comparisons=p1.comparisons + p2.comparisons,
            )
        )
    cells.append(
        QualCell(
            "19_api_ui_binding",
            "PENDING",
            0,
            "C5: analytics REST/UI binding on owner stack",
        )
    )
    return cells


def _seed_dataset(conn, *, ds, si_frame) -> None:
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    parity = cts._load_parity_module()
    with conn.cursor() as cur:
        cts.purge_site(cur, ds.building_id)
        cts.seed_frame(
            cur,
            parity,
            site_id=ds.building_id,
            equipment_id=ds.equipment_id,
            equip_type=ds.equipment_type,
            frame=si_frame,
            storage="si",
        )
        cts.fill_history(cur, ds.building_id, cts.frame_sql_columns(si_frame))
    conn.commit()


def run_postgres(conn) -> list[QualCell]:
    import datetime as dt

    metric = _metric()
    si_params = ap.resolve_params("metric", metric)
    golden = ap.load_analytics_goldens()
    as_of_raw = str(golden["evaluated_at"])
    as_of = dt.datetime.fromisoformat(as_of_raw.replace("Z", "+00:00"))
    stems = cap2.all_analytics_sql_stems()
    comparisons = 0
    errors: list[str] = []
    datasets = list(ap.iter_analytics_datasets())
    for ds in datasets:
        conn.rollback()
        si_frame = cfl.frame_to_si(ds.ip_frame, metric)
        ws, we = ap.window_of(si_frame)
        units = ap.role_units_of(ds.ip_frame)
        try:
            _seed_dataset(conn, ds=ds, si_frame=si_frame)
        except Exception as exc:
            errors.append(f"{ds.dataset_id}: seed {exc}")
            conn.rollback()
            continue
        for stem in stems:
            try:
                with conn.cursor() as cur:
                    sql_rows = cap2._exec_analytics_sql(
                        cur,
                        stem,
                        site_id=ds.building_id,
                        window_start=ws,
                        window_end=we,
                        equipment_ids=[ds.equipment_id],
                    )
            except Exception as exc:
                errors.append(f"{ds.dataset_id}/{stem}: sql {exc}")
                conn.rollback()
                continue
            sql_norm = ap.norm_rows(stem, list(sql_rows))
            oracle_rows = ap.pandas_rows(
                stem,
                si_frame,
                ds=ds,
                params=si_params,
                as_of=as_of,
                unit_system="metric",
                source_role_units=units,
                metric=metric,
            )
            oracle_norm = ap.norm_rows(stem, oracle_rows)
            if stem == "sensor_faults_staleness":
                flag_i = [c for c, _k in ap.STEM_COLUMNS[stem]].index("fault_flag")
                sql_trim = [r[:flag_i] for r in sql_norm]
                oracle_trim = [r[:flag_i] for r in oracle_norm]
                if len(sql_trim) != len(oracle_trim):
                    errors.append(
                        f"{ds.dataset_id}/{stem}: row count sql={len(sql_trim)} oracle={len(oracle_trim)}"
                    )
                    continue
                row_cmp = 0
                for g, l in zip(sorted(sql_trim, key=repr), sorted(oracle_trim, key=repr)):
                    row_cmp += 1
                    if len(g) != len(l):
                        errors.append(f"{ds.dataset_id}/{stem}: width mismatch")
                        break
                    for a, b in zip(g, l):
                        if isinstance(a, float) and isinstance(b, float):
                            if abs(a - b) > 1e-6 and not (abs(a) < 1e-9 and abs(b) < 1e-9):
                                errors.append(
                                    f"{ds.dataset_id}/{stem}: {a!r} != {b!r}"
                                )
                                break
                        elif a != b:
                            errors.append(f"{ds.dataset_id}/{stem}: {a!r} != {b!r}")
                            break
                comparisons += row_cmp
                continue
            n, e = ap.compare_rows(
                "C3-analytics-fresh",
                ds.dataset_id,
                stem,
                "sql_pg",
                sql_norm,
                "independent_oracle",
                oracle_norm,
            )
            comparisons += n
            if e:
                errors.extend(e[:2])
            elif n == 0:
                if not sql_norm and not oracle_norm:
                    continue
                if stem in ("plant_health_inventory",):
                    continue
                errors.append(f"{ds.dataset_id}/{stem}: zero comparisons")
    if errors:
        return [
            QualCell(
                "19_pg_fresh_sql_vs_oracle_all_bodies",
                "FAIL",
                comparisons,
                "; ".join(errors[:8]),
            )
        ]
    return [
        QualCell(
            "19_pg_fresh_sql_vs_oracle_all_bodies",
            "PASS",
            comparisons=comparisons,
            detail=f"stems={len(stems)} datasets={len(datasets)}",
        )
    ]
