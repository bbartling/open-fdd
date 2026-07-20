"""Golden-baseline harness for Overview / RCx / metering analytics + compact rule digests.

Used by tests to lock numeric outputs before performance work. Streamlit-free.
Timings are soft diagnostics — absolute seconds only fail when
``VIBE19_ASSERT_ANALYTICS_MAX_S`` is set.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.agent_api import AgentDataset, run_analytics, run_rcx_coverage, run_rules
from app.metering import build_meter_monthly_table
from app.occupancy import OccupancySchedule
from app.rcx_plots import (
    REQUIRED_RCX_PRESET_IDS,
    collect_oat_scatter,
    collect_role_series,
    preset_by_id,
    series_summary_stats,
    zone_comfort_fail_ranking,
)

FLOAT_DECIMALS = 6
NAN_SENTINEL = "__NA__"
UPDATE_ENV = "VIBE19_UPDATE_ANALYTICS_GOLDEN"
ASSERT_MAX_S_ENV = "VIBE19_ASSERT_ANALYTICS_MAX_S"

# Stable table names written under tests/golden/analytics/
GOLDEN_TABLE_NAMES: tuple[str, ...] = (
    "motor_hours",
    "motor_weekly",
    "mech_cooling_oat_bins",
    "economizer_weather",
    "rcx_preset_coverage",
    "rcx_preset_digests",
    "rule_digest",
)


@dataclass
class AnalyticsBundle:
    """Named canonical tables + wall-clock timings (seconds)."""

    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    timings_s: dict[str, float] = field(default_factory=dict)


def canonicalize_frame(df: pd.DataFrame, *, float_decimals: int = FLOAT_DECIMALS) -> pd.DataFrame:
    """Stable column order, sorted rows, rounded floats, NaN → sentinel string."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    # Flatten MultiIndex columns if any
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = ["__".join(str(x) for x in tup) for tup in out.columns.to_list()]
    out.columns = [str(c) for c in out.columns]
    cols = sorted(out.columns)
    out = out.loc[:, cols]
    for c in out.columns:
        if pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else ("True" if bool(v) else "False"))
        elif pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = pd.to_datetime(out[c], utc=True, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            out[c] = out[c].fillna(NAN_SENTINEL)
        elif pd.api.types.is_numeric_dtype(out[c]):
            num = pd.to_numeric(out[c], errors="coerce")
            out[c] = num.round(float_decimals).map(
                lambda v: NAN_SENTINEL if pd.isna(v) else f"{float(v):.{float_decimals}f}"
            )
        else:
            out[c] = out[c].map(lambda v: NAN_SENTINEL if pd.isna(v) else str(v))
    # Sort by all columns for deterministic row order
    if len(out.columns):
        out = out.sort_values(by=list(out.columns), kind="mergesort").reset_index(drop=True)
    return out


def frame_to_canonical_csv(df: pd.DataFrame) -> str:
    can = canonicalize_frame(df)
    buf = io.StringIO()
    can.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def fingerprint_frame(df: pd.DataFrame) -> str:
    """SHA256 of canonical CSV (hex)."""
    return hashlib.sha256(frame_to_canonical_csv(df).encode("utf-8")).hexdigest()


def _digest_series_map(preset_id: str, series_map: dict[str, pd.Series]) -> pd.DataFrame:
    stats = series_summary_stats(series_map, outlier_z=2.5)
    if stats.empty:
        return pd.DataFrame(
            columns=[
                "preset_id",
                "equipment_id",
                "n",
                "mean",
                "std",
                "min",
                "p25",
                "p50",
                "p75",
                "max",
                "outlier",
            ]
        )
    out = stats.copy()
    out.insert(0, "preset_id", preset_id)
    return out


def _digest_scatter(preset_id: str, long_df: pd.DataFrame) -> pd.DataFrame:
    if long_df is None or long_df.empty:
        return pd.DataFrame(
            columns=["preset_id", "equipment_id", "n", "mean_y", "mean_oat", "min_y", "max_y"]
        )
    rows: list[dict[str, Any]] = []
    eq_col = "equipment_id" if "equipment_id" in long_df.columns else None
    if eq_col is None:
        rows.append(
            {
                "preset_id": preset_id,
                "equipment_id": "_all_",
                "n": int(len(long_df)),
                "mean_y": float(pd.to_numeric(long_df["y"], errors="coerce").mean()),
                "mean_oat": float(pd.to_numeric(long_df["oat"], errors="coerce").mean()),
                "min_y": float(pd.to_numeric(long_df["y"], errors="coerce").min()),
                "max_y": float(pd.to_numeric(long_df["y"], errors="coerce").max()),
            }
        )
    else:
        for eq_id, g in long_df.groupby(eq_col, sort=True):
            y = pd.to_numeric(g["y"], errors="coerce")
            oat = pd.to_numeric(g["oat"], errors="coerce")
            rows.append(
                {
                    "preset_id": preset_id,
                    "equipment_id": str(eq_id),
                    "n": int(y.notna().sum()),
                    "mean_y": float(y.mean()) if y.notna().any() else float("nan"),
                    "mean_oat": float(oat.mean()) if oat.notna().any() else float("nan"),
                    "min_y": float(y.min()) if y.notna().any() else float("nan"),
                    "max_y": float(y.max()) if y.notna().any() else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def compute_rcx_preset_digests(
    dataset: AgentDataset,
    *,
    schedule: OccupancySchedule | None = None,
    zone_lo_f: float = 70.0,
    zone_hi_f: float = 75.0,
    outlier_z: float = 2.5,
) -> pd.DataFrame:
    """Per-required-preset numeric digests (summary stats / scatter / ranking / metering)."""
    sched = schedule or OccupancySchedule()
    parts: list[pd.DataFrame] = []
    frames = dataset.frames
    role_map = dataset.role_map
    weather = dataset.weather

    for pid in sorted(REQUIRED_RCX_PRESET_IDS):
        preset = preset_by_id(pid)
        if preset is None:
            continue
        chart = preset.chart
        if chart == "ranking":
            rank = zone_comfort_fail_ranking(
                frames,
                role_map,
                schedule=sched,
                comfort_low_f=zone_lo_f,
                comfort_high_f=zone_hi_f,
                equipment_types=preset.equipment_types,
                outlier_z=outlier_z,
            )
            if rank.empty:
                parts.append(
                    pd.DataFrame(
                        [
                            {
                                "preset_id": pid,
                                "equipment_id": "_empty_",
                                "n": 0,
                                "mean": float("nan"),
                                "std": float("nan"),
                                "min": float("nan"),
                                "p25": float("nan"),
                                "p50": float("nan"),
                                "p75": float("nan"),
                                "max": float("nan"),
                                "outlier": False,
                            }
                        ]
                    )
                )
            else:
                dig = rank.copy()
                dig.insert(0, "preset_id", pid)
                # Keep ranking columns as digest payload
                parts.append(dig)
            continue

        if chart == "metering":
            kind = "electric" if pid == "meter_elec_cdd" else "gas"
            monthly, stats, _reason = build_meter_monthly_table(
                frames,
                role_map,
                kind=kind,  # type: ignore[arg-type]
                weather=weather,
                equipment_types=preset.equipment_types,
            )
            if not stats.empty:
                s = stats.copy()
                s.insert(0, "preset_id", pid)
                s.insert(1, "digest_kind", "meter_stats")
                parts.append(s)
            if not monthly.empty:
                m = monthly.copy()
                m.insert(0, "preset_id", pid)
                m.insert(1, "digest_kind", "meter_monthly")
                parts.append(m)
            if stats.empty and monthly.empty:
                parts.append(
                    pd.DataFrame(
                        [{"preset_id": pid, "digest_kind": "meter_empty", "equipment_id": "_empty_", "n": 0}]
                    )
                )
            continue

        if chart == "scatter_oat":
            x_pref = "wetbulb" if pid == "cw_reset_scatter" else "web"
            long_df = collect_oat_scatter(
                frames,
                role_map,
                y_role=preset.role,
                weather=weather,
                equipment_types=preset.equipment_types,
                x_prefer=x_pref,
            )
            parts.append(_digest_scatter(pid, long_df))
            continue

        # timeseries / box
        series_map = collect_role_series(
            frames,
            role_map,
            role=preset.role,
            equipment_types=preset.equipment_types,
            filter_fan_on=preset.filter_fan_on,
        )
        parts.append(_digest_series_map(pid, series_map))

    if not parts:
        return pd.DataFrame()
    # Drop all-empty frames so concat stays stable across pandas versions
    nonempty = [p for p in parts if p is not None and not p.empty]
    if not nonempty:
        return pd.DataFrame()
    return pd.concat(nonempty, ignore_index=True, sort=False)


def rule_results_to_digest(results: list[Any]) -> pd.DataFrame:
    """Compact per-(equipment, rule) digest — status + counts, not fault masks."""
    rows: list[dict[str, Any]] = []
    for r in results:
        metrics = getattr(r, "metrics", None) or {}
        # Count-like / gate labels only (stable strings / ints / floats)
        gate_kind = metrics.get("gate_kind", "")
        gate_source = metrics.get("gate_source", "")
        gate_applied = metrics.get("gate_applied", "")
        rows.append(
            {
                "equipment_id": str(getattr(r, "equipment_id", "")),
                "rule_id": str(getattr(r, "rule_id", "")),
                "status": str(getattr(r, "status", "")),
                "equipment_type": str(getattr(r, "equipment_type", "")),
                "fault_hours": getattr(r, "fault_hours", None),
                "fault_pct": getattr(r, "fault_pct", None),
                "sample_count": int(getattr(r, "sample_count", 0) or 0),
                "fault_sample_count": int(getattr(r, "fault_sample_count", 0) or 0),
                "gate_kind": str(gate_kind) if gate_kind is not None else "",
                "gate_source": str(gate_source) if gate_source is not None else "",
                "gate_applied": str(gate_applied) if gate_applied is not None else "",
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "equipment_id",
                "rule_id",
                "status",
                "equipment_type",
                "fault_hours",
                "fault_pct",
                "sample_count",
                "fault_sample_count",
                "gate_kind",
                "gate_source",
                "gate_applied",
            ]
        )
    return pd.DataFrame(rows)


def compute_analytics_bundle(
    dataset: AgentDataset,
    *,
    schedule: OccupancySchedule | None = None,
    zone_lo_f: float = 70.0,
    zone_hi_f: float = 75.0,
    run_rules_digest: bool = True,
    require_operational_gates: bool = True,
) -> AnalyticsBundle:
    """Compute all golden tables + soft timings."""
    timings: dict[str, float] = {}
    tables: dict[str, pd.DataFrame] = {}

    t0 = time.perf_counter()
    analytics = run_analytics(dataset)
    timings["analytics_s"] = time.perf_counter() - t0
    tables["motor_hours"] = analytics.get("motor_hours", pd.DataFrame())
    tables["motor_weekly"] = analytics.get("motor_weekly", pd.DataFrame())
    tables["mech_cooling_oat_bins"] = analytics.get("mech_cooling_oat_bins", pd.DataFrame())
    tables["economizer_weather"] = analytics.get("economizer_weather", pd.DataFrame())

    t0 = time.perf_counter()
    tables["rcx_preset_coverage"] = run_rcx_coverage(dataset)
    tables["rcx_preset_digests"] = compute_rcx_preset_digests(
        dataset,
        schedule=schedule,
        zone_lo_f=zone_lo_f,
        zone_hi_f=zone_hi_f,
    )
    timings["rcx_s"] = time.perf_counter() - t0

    if run_rules_digest:
        t0 = time.perf_counter()
        run = run_rules(dataset, require_operational_gates=require_operational_gates)
        tables["rule_digest"] = rule_results_to_digest(run.results)
        timings["rules_s"] = time.perf_counter() - t0
    else:
        tables["rule_digest"] = pd.DataFrame()
        timings["rules_s"] = 0.0

    return AnalyticsBundle(tables=tables, timings_s=timings)


def golden_dir_default() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "golden" / "analytics"


def write_golden_tables(bundle: AnalyticsBundle, out_dir: Path | None = None) -> dict[str, Path]:
    """Write canonical CSVs for each golden table. Returns path map."""
    root = out_dir or golden_dir_default()
    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in GOLDEN_TABLE_NAMES:
        df = bundle.tables.get(name, pd.DataFrame())
        path = root / f"{name}.csv"
        path.write_text(frame_to_canonical_csv(df), encoding="utf-8")
        written[name] = path
    digests = {name: fingerprint_frame(bundle.tables.get(name, pd.DataFrame())) for name in GOLDEN_TABLE_NAMES}
    digest_path = root / "fingerprints.json"
    import json

    digest_path.write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written["fingerprints"] = digest_path
    return written


def load_golden_csv(name: str, golden_dir: Path | None = None) -> pd.DataFrame:
    root = golden_dir or golden_dir_default()
    path = root / f"{name}.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def assert_matches_golden(
    bundle: AnalyticsBundle,
    *,
    golden_dir: Path | None = None,
    update: bool | None = None,
) -> None:
    """Compare bundle tables to committed CSVs (or rewrite when update env set)."""
    root = golden_dir or golden_dir_default()
    do_update = bool(update) if update is not None else os.environ.get(UPDATE_ENV, "").strip() in {
        "1",
        "true",
        "True",
        "yes",
        "YES",
    }
    if do_update:
        write_golden_tables(bundle, root)
        return

    mismatches: list[str] = []
    for name in GOLDEN_TABLE_NAMES:
        got_csv = frame_to_canonical_csv(bundle.tables.get(name, pd.DataFrame()))
        path = root / f"{name}.csv"
        if not path.is_file():
            mismatches.append(f"{name}: missing golden file {path}")
            continue
        want_csv = path.read_text(encoding="utf-8")
        # Normalize newlines
        if want_csv.replace("\r\n", "\n") != got_csv:
            mismatches.append(
                f"{name}: golden mismatch (sha got={fingerprint_frame(bundle.tables.get(name, pd.DataFrame()))})"
            )
    if mismatches:
        hint = f"Set {UPDATE_ENV}=1 to regenerate goldens after intentional analytics changes."
        raise AssertionError("Analytics golden mismatch:\n- " + "\n- ".join(mismatches) + f"\n{hint}")


def maybe_assert_timings(timings_s: dict[str, float], *, load_s: float | None = None) -> dict[str, float]:
    """Return report; optionally fail if ASSERT_MAX_S_ENV total exceeded."""
    report = dict(timings_s)
    if load_s is not None:
        report["load_s"] = float(load_s)
    report["total_s"] = float(sum(v for k, v in report.items() if k.endswith("_s")))
    raw = os.environ.get(ASSERT_MAX_S_ENV, "").strip()
    if raw:
        limit = float(raw)
        if report["total_s"] > limit:
            raise AssertionError(
                f"Analytics timing {report['total_s']:.3f}s exceeds {ASSERT_MAX_S_ENV}={limit}"
            )
    return report


def fingerprints_for_bundle(bundle: AnalyticsBundle) -> dict[str, str]:
    return {name: fingerprint_frame(bundle.tables.get(name, pd.DataFrame())) for name in GOLDEN_TABLE_NAMES}
