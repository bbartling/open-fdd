"""Importable Agent API for AFDD / RCx — no HTTP server, Streamlit-free.

Agents load packages/folders, run the 50-rule cookbook, analytics, and RCx
coverage, then export a machine-readable bundle.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from app.analytics import (
    dataset_time_span,
    economizer_weather_summary,
    mech_cooling_coverage,
    mech_cooling_oat_bins,
    motor_run_hours_table,
    motor_run_hours_weekly,
)
from app.model_seed import (
    build_model_seed_dict,
    infer_schedules,
    operating_signatures,
)
from app.column_map_json import (
    merge_column_map_into_role_map,
    to_haystack_document,
)
from app.data_loader import load_building_folder as _load_building_folder_frames
from app.data_loader import load_equipment_csv
from app.package_io import (
    SESSION_SCHEMA,
    load_package_from_dir,
    load_package_zip,
    resolve_building_root,
)
from app.reports import results_summary_table
from app.role_map_gap import build_role_map_gap_report
from app.rules.base import RuleResult
from app.rules.runner import RULES, run_batch
from app.site_model import resolve_equipment_type, stamp_equipment_type
from app.tuning_report import build_tuning_assistant_report
from app.weather_psychrometrics import enrich_weather_frame
from app.weather_resolver import has_web_oat


@dataclass
class AgentDataset:
    """Loaded building data ready for rules / analytics / RCx."""

    building_id: str
    frames: dict[str, pd.DataFrame]
    weather: pd.DataFrame | None
    role_map: dict[str, dict[str, str]] = field(default_factory=dict)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    unit_system: str = "imperial"
    prefer_web_oat: bool = True
    chw_leave_max_f: float = 48.0
    use_mech_cooling_status_proof: bool = True
    column_map: dict[str, Any] | None = None
    package_report: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source_path: str = ""
    workdir: Path | None = None
    session_config: dict[str, Any] | None = None

    @property
    def has_web_weather(self) -> bool:
        return has_web_oat(self.weather)


@dataclass
class AgentRun:
    """Results from ``run_rules`` (and optional analytics / RCx attachments)."""

    results: list[RuleResult] = field(default_factory=list)
    summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    status_counts: dict[str, int] = field(default_factory=dict)
    top_faults: pd.DataFrame = field(default_factory=pd.DataFrame)
    analytics: dict[str, pd.DataFrame] = field(default_factory=dict)
    rcx_coverage: pd.DataFrame = field(default_factory=pd.DataFrame)
    gap_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    tuning_report: dict[str, Any] = field(default_factory=dict)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def make_session_config(
    role_map: dict[str, dict[str, str]] | None = None,
    params: dict[str, dict[str, Any]] | None = None,
    *,
    unit_system: str = "imperial",
    prefer_web_oat: bool = True,
    chw_leave_max_f: float | None = None,
    use_mech_cooling_status_proof: bool = True,
    include_ahu_chw_valve: bool | None = None,
) -> dict[str, Any]:
    """Build an ``openfdd_session_v1`` dict suitable for JSON export.

    ``include_ahu_chw_valve`` is accepted for API compat but **always exported as
    False** — mech-cooling OAT bins never use AHU CHW cooling valves.
    """
    del include_ahu_chw_valve  # deprecated; never enable valve-as-cooling
    out: dict[str, Any] = {
        "schema_version": SESSION_SCHEMA,
        "unit_system": unit_system,
        "prefer_web_oat": bool(prefer_web_oat),
        "use_mech_cooling_status_proof": bool(use_mech_cooling_status_proof),
        "role_map": role_map or {},
        "params": params or {},
        "include_ahu_chw_valve": False,
    }
    if chw_leave_max_f is not None:
        out["chw_leave_max_f"] = float(chw_leave_max_f)
    return out


def _attach_role_map(frames: dict[str, pd.DataFrame], role_map: dict[str, dict[str, str]]) -> None:
    for eq_id, df in frames.items():
        df.attrs["_role_map"] = role_map
        df.attrs.setdefault("equipment_id", eq_id)
        stamp_equipment_type(df, eq_id, role_map=role_map)


def _load_weather_near(building_root: Path) -> pd.DataFrame | None:
    candidates = [
        building_root / "weather" / "history_wide.csv",
        building_root.parent / "weather" / "history_wide.csv",
    ]
    for hist in candidates:
        if not hist.is_file():
            continue
        cols = hist.parent / "columns.csv"
        try:
            df = load_equipment_csv(hist, cols if cols.is_file() else None)
            return enrich_weather_frame(df)
        except Exception:
            continue
    return None


def _dataset_from_package(result, *, source_path: str) -> AgentDataset:
    role_map: dict[str, dict[str, str]] = {}
    params: dict[str, dict[str, Any]] = {}
    unit_system = "imperial"
    prefer_web = True
    chw_leave_max_f = 48.0
    use_status_proof = True
    session_dict: dict[str, Any] | None = None

    if result.session_config is not None:
        cfg = result.session_config
        session_dict = cfg.model_dump()
        if cfg.role_map:
            role_map = {str(k): dict(v) for k, v in cfg.role_map.items() if isinstance(v, dict)}
        if cfg.params:
            params = {str(k): dict(v) for k, v in cfg.params.items() if isinstance(v, dict)}
        if cfg.unit_system:
            unit_system = cfg.unit_system
        if cfg.prefer_web_oat is not None:
            prefer_web = bool(cfg.prefer_web_oat)
        if cfg.chw_leave_max_f is not None:
            chw_leave_max_f = float(cfg.chw_leave_max_f)
        if cfg.use_mech_cooling_status_proof is not None:
            use_status_proof = bool(cfg.use_mech_cooling_status_proof)

    if result.column_map:
        role_map = merge_column_map_into_role_map(role_map, result.column_map, prefer_json=True)

    frames = result.frames
    for eq_id, df in frames.items():
        df.attrs.setdefault("building_id", result.manifest.building_id)
        stamp_equipment_type(
            df,
            eq_id,
            role_map=role_map,
            column_map=result.column_map,
        )
    _attach_role_map(frames, role_map)

    return AgentDataset(
        building_id=result.manifest.building_id,
        frames=frames,
        weather=result.weather,
        role_map=role_map,
        params=params,
        unit_system=unit_system,
        prefer_web_oat=prefer_web,
        chw_leave_max_f=chw_leave_max_f,
        use_mech_cooling_status_proof=use_status_proof,
        column_map=result.column_map,
        package_report=dict(result.report),
        warnings=list(result.warnings),
        source_path=source_path,
        workdir=Path(result.workdir) if result.workdir else None,
        session_config=session_dict,
    )


def load_package_path(path: str | Path) -> AgentDataset:
    """Load an ``openfdd_package_v1`` zip or an already-extracted package directory."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Package path not found: {p}")
    if p.is_file() and p.suffix.lower() == ".zip":
        result = load_package_zip(p.read_bytes())
        return _dataset_from_package(result, source_path=str(p))
    if p.is_dir():
        # Extracted package (has manifest) or workdir containing one child
        try:
            root = resolve_building_root(p) if not (p / "manifest.json").is_file() else p
        except Exception:
            root = p
        if (root / "manifest.json").is_file():
            result = load_package_from_dir(root, workdir=p)
            return _dataset_from_package(result, source_path=str(p))
        # Fall through to folder loader
        return load_building_folder(p)
    raise ValueError(f"Unsupported package path: {p}")


def load_building_folder(path: str | Path) -> AgentDataset:
    """Load a historian building folder (equipment subdirs + optional weather)."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"Building folder not found: {p}")
    # Prefer package loader when manifest present
    if (p / "manifest.json").is_file():
        result = load_package_from_dir(p, workdir=p)
        return _dataset_from_package(result, source_path=str(p))

    frames = _load_building_folder_frames(p)
    if not frames:
        raise ValueError(f"No equipment frames under {p}")
    weather = _load_weather_near(p)
    role_map: dict[str, dict[str, str]] = {}
    params: dict[str, dict[str, Any]] = {}
    session_dict = None
    sc_path = p / "session_config.json"
    if sc_path.is_file():
        try:
            from app.package_io import SessionConfig

            raw = json.loads(sc_path.read_text(encoding="utf-8"))
            cfg = SessionConfig.model_validate(raw)
            session_dict = cfg.model_dump()
            if cfg.role_map:
                role_map = {str(k): dict(v) for k, v in cfg.role_map.items() if isinstance(v, dict)}
            if cfg.params:
                params = {str(k): dict(v) for k, v in cfg.params.items() if isinstance(v, dict)}
        except Exception:
            pass
    cm_path = p / "column_map.json"
    column_map = None
    warnings: list[str] = []
    if cm_path.is_file():
        from app.column_map_json import load_column_map_json, validate_column_map_against_frames

        column_map = load_column_map_json(cm_path)
        role_map = merge_column_map_into_role_map(role_map, column_map, prefer_json=True)
        warnings.extend(validate_column_map_against_frames(column_map, frames)[:20])

    for eq_id, df in frames.items():
        df.attrs.setdefault("building_id", p.name)
        stamp_equipment_type(df, eq_id, role_map=role_map, column_map=column_map)
    _attach_role_map(frames, role_map)
    span = dataset_time_span(frames)
    report = {
        "building_id": p.name,
        "equipment_count": len(frames),
        "equipment_ids": sorted(frames),
        "has_weather": weather is not None,
        "has_session_config": session_dict is not None,
        "has_column_map": column_map is not None,
        "start": str(span["start"]) if span.get("start") is not None else None,
        "end": str(span["end"]) if span.get("end") is not None else None,
    }
    return AgentDataset(
        building_id=p.name,
        frames=frames,
        weather=weather,
        role_map=role_map,
        params=params,
        column_map=column_map,
        package_report=report,
        warnings=warnings,
        source_path=str(p),
        session_config=session_dict,
    )


def run_rules(
    dataset: AgentDataset,
    params: dict[str, dict[str, Any]] | None = None,
    equipment_ids: list[str] | set[str] | None = None,
    rule_ids: list[str] | set[str] | None = None,
    *,
    require_operational_gates: bool = True,
) -> AgentRun:
    """Run FDD via central DataFusion SQL (default). Pandas only if explicitly allowed."""
    import os

    from app import central_client
    from app.rules.base import RuleResult

    merged_params = {**dataset.params, **(params or {})}
    eq_filter = set(equipment_ids) if equipment_ids is not None else None
    t_rules = time.perf_counter()

    allow_pandas = (os.environ.get("OPENFDD_ALLOW_PANDAS_FDD") or "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }
    engine = "datafusion"

    if not allow_pandas:
        # Prefer SQL — dataset must already be ingested to central (same building_id).
        float_params: dict[str, dict[str, float]] = {}
        for rid, block in merged_params.items():
            if not isinstance(block, dict):
                continue
            float_params[str(rid)] = {
                str(k): float(v) for k, v in block.items() if isinstance(v, (int, float))
            }
        selected_rules = list(rule_ids) if rule_ids is not None else [r.id for r in RULES]
        equipment_id = None
        if eq_filter is not None and len(eq_filter) == 1:
            equipment_id = next(iter(eq_filter))
        body = central_client.run_fdd(
            rule_ids=selected_rules,
            params=float_params or None,
            equipment_id=equipment_id,
        )
        if not body.get("ok", False):
            err = body.get("error") or "SQL FDD run failed"
            raise RuntimeError(
                f"{err} (set OPENFDD_ALLOW_PANDAS_FDD=1 only for emergency local pandas)"
            )
        rows = body.get("results") or []
        if not isinstance(rows, list) or not rows:
            cached = central_client.fdd_results()
            rows = cached.get("results") or []
        if eq_filter is not None:
            rows = [
                r
                for r in rows
                if isinstance(r, dict) and r.get("equipment_id") in eq_filter
            ]
        if rule_ids is not None:
            allow = set(rule_ids)
            rows = [r for r in rows if isinstance(r, dict) and r.get("rule_id") in allow]
        meta = {r.id: r for r in RULES}
        results: list[RuleResult] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("rule_id") or "")
            eq = str(row.get("equipment_id") or "")
            if not rid or not eq:
                continue
            rule = meta.get(rid)
            title = str(row.get("title") or (getattr(rule, "title", "") if rule else "") or rid)
            status = str(row.get("status") or "PASS")
            fh = row.get("fault_hours")
            fp = row.get("fault_pct")
            notes = row.get("notes")
            if notes is not None and not isinstance(notes, str):
                notes = str(notes)
            results.append(
                RuleResult(
                    rule_id=rid,
                    equipment_id=eq,
                    status=status,  # type: ignore[arg-type]
                    applicable=status not in {"NOT_APPLICABLE_EQUIPMENT_TYPE"},
                    equipment_type=str(row.get("equipment_type") or ""),
                    building_id=str(dataset.building_id or ""),
                    missing_roles=list(row.get("missing_roles") or []),
                    fault_hours=float(fh) if fh is not None else None,
                    fault_pct=float(fp) if fp is not None else None,
                    notes=notes or f"DataFusion SQL · {title}",
                )
            )
    else:
        engine = "pandas"
        _attach_role_map(dataset.frames, dataset.role_map)
        if require_operational_gates:
            results = run_batch(
                dataset.frames,
                params_by_rule=merged_params,
                weather=dataset.weather,
                equipment_filter=eq_filter,
            )
        else:
            from app.role_map import apply_role_map
            from app.rules.runner import run_all_cookbook_rules

            results = []
            for eq_id, raw_df in sorted(dataset.frames.items()):
                if eq_filter is not None and eq_id not in eq_filter:
                    continue
                mapped = apply_role_map(raw_df, eq_id, dataset.role_map)
                mapped.attrs.update(raw_df.attrs)
                poll = float(raw_df.attrs.get("poll_seconds") or 300.0)
                results.extend(
                    run_all_cookbook_rules(
                        mapped,
                        equipment_id=eq_id,
                        poll_seconds=poll,
                        params_by_rule=merged_params,
                        weather=dataset.weather,
                        site_id=str(raw_df.attrs.get("site_id", "")),
                        building_id=str(raw_df.attrs.get("building_id", dataset.building_id)),
                        equipment_type=resolve_equipment_type(
                            eq_id, df=raw_df, role_map=dataset.role_map
                        ),
                        require_operational_gates=False,
                    )
                )
        if rule_ids is not None:
            allow = set(rule_ids)
            results = [r for r in results if r.rule_id in allow]

    rule_execution_seconds = round(time.perf_counter() - t_rules, 6)
    # Ensure every requested rule id still appears conceptually — when filtering,
    # callers asked for a subset; full catalog length is len(RULES)*equip when unfiltered.
    summary = results_summary_table(results)
    counts = (
        {str(k): int(v) for k, v in summary["status"].value_counts().to_dict().items()}
        if not summary.empty
        else {}
    )
    top = pd.DataFrame()
    if not summary.empty:
        faults = summary[summary["status"] == "FAULT"].copy()
        if not faults.empty and "fault_hours" in faults.columns:
            top = faults.sort_values("fault_hours", ascending=False).head(25)
    return AgentRun(
        results=results,
        summary=summary,
        status_counts=counts,
        top_faults=top,
        params=merged_params,
        meta={
            "building_id": dataset.building_id,
            "equipment_count": len(dataset.frames),
            "rule_catalog_count": len(RULES),
            "result_count": len(results),
            "has_web_weather": dataset.has_web_weather,
            "prefer_web_oat": dataset.prefer_web_oat,
            "require_operational_gates": require_operational_gates,
            "rule_execution_seconds": rule_execution_seconds,
            "fdd_engine": engine,
        },
    )


def run_analytics(
    dataset: AgentDataset,
    params: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    """Motor hours, weekly motors, mech-cooling OAT bins, model-seed signatures."""
    p = params or {}
    prefer_web = bool(p.get("prefer_web_oat", dataset.prefer_web_oat))
    chw_leave_max_f = float(p.get("chw_leave_max_f", dataset.chw_leave_max_f))
    use_status_proof = bool(
        p.get(
            "use_mech_cooling_status_proof",
            dataset.use_mech_cooling_status_proof,
        )
    )
    motor = motor_run_hours_table(dataset.frames, dataset.role_map)
    weekly = motor_run_hours_weekly(
        dataset.frames,
        dataset.role_map,
        chw_leave_max_f=chw_leave_max_f,
        weather=dataset.weather,
        prefer_web_oat=prefer_web,
    )
    cool = mech_cooling_oat_bins(
        dataset.frames,
        dataset.role_map,
        weather=dataset.weather,
        prefer_web_oat=prefer_web,
        chw_leave_max_f=chw_leave_max_f,
        include_ahu_chw_valve=False,
        include_total=True,
        use_status_proof=use_status_proof,
    )
    cool_cov = mech_cooling_coverage(
        dataset.frames,
        dataset.role_map,
        weather=dataset.weather,
        prefer_web_oat=prefer_web,
        chw_leave_max_f=chw_leave_max_f,
        use_status_proof=use_status_proof,
    )
    econ = economizer_weather_summary(
        dataset.frames,
        dataset.role_map,
        weather=dataset.weather,
        damper_hi=float(p.get("econ3_damper_hi", 0.90)),
        damper_winter_max=float(p.get("econ6_damper_max", 0.25)),
    )
    sched_table, sched_payload = infer_schedules(dataset.frames, dataset.role_map)
    signatures = operating_signatures(
        dataset.frames,
        dataset.role_map,
        weather=dataset.weather,
        prefer_web_oat=prefer_web,
    )
    return {
        "motor_hours": motor,
        "motor_weekly": weekly,
        "mech_cooling_oat_bins": cool,
        "mech_cooling_coverage": cool_cov,
        "economizer_weather": econ,
        "schedule_inference_table": sched_table,
        "schedule_inference": sched_payload,
        "operating_signatures": signatures,
    }


def run_rcx_coverage(dataset: AgentDataset) -> pd.DataFrame:
    """RCx preset coverage diagnostics."""
    from app.rcx_plots import rcx_preset_coverage

    return rcx_preset_coverage(dataset.frames, dataset.role_map, weather=dataset.weather)


def export_agent_bundle(
    dataset: AgentDataset,
    run: AgentRun | None,
    out_dir: str | Path,
    *,
    include_gap_report: bool = True,
    include_tuning_report: bool = True,
    baseline_run: AgentRun | None = None,
    utility_bills: list[dict[str, Any]] | None = None,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    include_bootstrap: bool = True,
    profile: str = "summary",
    selected_evidence: set[tuple[str, str]] | None = None,
) -> dict[str, Path]:
    """Write run_report + CSVs + model-seed artifacts under ``out_dir``.

    ``profile`` controls FDD evidence volume (``summary`` / ``diagnostic`` /
    ``forensic``). Default ``summary`` keeps sensor/setpoint/model-seed/analytic
    artifacts and shared telemetry without a Cartesian per-rule timeseries dump.
    """
    from app.wattlab_dump import EXPORT_PROFILES, ExportProfile

    if profile not in EXPORT_PROFILES:
        raise ValueError(f"Unknown export profile: {profile!r}; expected one of {EXPORT_PROFILES}")
    export_profile: ExportProfile = profile  # type: ignore[assignment]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    export_counts = None
    stage_seconds: dict[str, float] = {
        "rule_execution": 0.0,
        "analytics": 0.0,
        "serialization": 0.0,
        "compression": 0.0,
    }

    run = run or AgentRun(params=dataset.params)
    # Rule execution is typically done before export; credit any recorded timing.
    if isinstance(run.meta, dict) and run.meta.get("rule_execution_seconds") is not None:
        try:
            stage_seconds["rule_execution"] = float(run.meta["rule_execution_seconds"])
        except (TypeError, ValueError):
            stage_seconds["rule_execution"] = 0.0

    t_analytics = time.perf_counter()
    analytics = run.analytics or {}
    if not analytics:
        analytics = run_analytics(dataset)
        run.analytics = analytics
    # Ensure model-seed analytics even for older AgentRun objects
    if "schedule_inference" not in analytics or "operating_signatures" not in analytics:
        sched_table, sched_payload = infer_schedules(dataset.frames, dataset.role_map)
        signatures = operating_signatures(
            dataset.frames,
            dataset.role_map,
            weather=dataset.weather,
            prefer_web_oat=dataset.prefer_web_oat,
        )
        analytics["schedule_inference_table"] = sched_table
        analytics["schedule_inference"] = sched_payload
        analytics["operating_signatures"] = signatures
        run.analytics = analytics

    rcx = run.rcx_coverage
    if rcx is None or (isinstance(rcx, pd.DataFrame) and rcx.empty):
        rcx = run_rcx_coverage(dataset)
        run.rcx_coverage = rcx

    gap = run.gap_report
    if include_gap_report and (gap is None or (isinstance(gap, pd.DataFrame) and gap.empty)):
        gap = build_role_map_gap_report(dataset.frames, dataset.role_map, weather=dataset.weather)
        run.gap_report = gap

    if include_tuning_report and not run.tuning_report:
        run.tuning_report = build_tuning_assistant_report(
            baseline=baseline_run.results if baseline_run else None,
            tuned=run.results,
            params=run.params or dataset.params,
            has_web_weather=dataset.has_web_weather,
            gap_report=gap if isinstance(gap, pd.DataFrame) else None,
        )
    stage_seconds["analytics"] = round(time.perf_counter() - t_analytics, 6)

    results_list = list(run.results or [])
    status_counts = dict(run.status_counts or {})
    if not status_counts and results_list:
        from collections import Counter

        status_counts = dict(Counter(r.status for r in results_list))
    applicable_count = sum(1 for r in results_list if getattr(r, "applicable", False))
    non_applicable_count = max(0, len(results_list) - applicable_count)

    # Serialization covers writing payload files (including final run_report.json).
    # Analytics above is compute-only; MANIFEST is written after payload measurement.
    t_serialize = time.perf_counter()

    from app.wattlab_dump import (
        EXPORT_METRICS_SCOPE,
        EXPORT_STAGE_SCOPE,
        diurnal_profiles,
        fdd_findings_table,
        sensor_stats_tables,
        setpoints_table,
        write_fdd_evidence,
        write_manifest,
        write_shared_telemetry,
        write_wattlab_readme,
    )

    health = (dataset.package_report or {}).get("package_health")
    if health:
        ph = out / "package_health.json"
        ph.write_text(json.dumps(health, indent=2, default=str), encoding="utf-8")
        written["package_health"] = ph

    if run.summary is not None and not run.summary.empty:
        p = out / "fdd_summary.csv"
        run.summary.to_csv(p, index=False)
        written["fdd_summary"] = p
    elif run.results:
        summary = results_summary_table(run.results)
        if not summary.empty:
            p = out / "fdd_summary.csv"
            summary.to_csv(p, index=False)
            written["fdd_summary"] = p
            run.summary = summary

    # Long-format findings + profile-aware evidence + shared telemetry
    if run.results:
        findings = fdd_findings_table(run.results)
        if isinstance(findings, pd.DataFrame) and not findings.empty:
            p = out / "fdd_findings.csv"
            findings.to_csv(p, index=False)
            written["fdd_findings"] = p
        export_counts = write_fdd_evidence(
            run.results,
            out,
            profile=export_profile,
            selected_evidence=selected_evidence,
            frames=dataset.frames,
            role_map=dataset.role_map,
        )
        for ts_path in export_counts.written:
            rel = ts_path.relative_to(out).as_posix()
            written[f"fdd_timeseries:{rel}"] = ts_path

    for eq_id, tel_path in write_shared_telemetry(
        dataset.frames,
        dataset.role_map,
        out,
        profile=export_profile,
        results=run.results,
        selected_evidence=selected_evidence,
    ).items():
        written[f"telemetry:{eq_id}"] = tel_path

    fault_settings = run.params or dataset.params or {}
    fs = out / "fault_settings.json"
    fs.write_text(json.dumps(fault_settings, indent=2), encoding="utf-8")
    written["fault_settings"] = fs

    session = make_session_config(
        dataset.role_map,
        fault_settings,
        unit_system=dataset.unit_system,
        prefer_web_oat=dataset.prefer_web_oat,
    )
    sc = out / "session_config.json"
    sc.write_text(json.dumps(session, indent=2), encoding="utf-8")
    written["session_config"] = sc

    rm = out / "role_map.yaml"
    rm.write_text(yaml.safe_dump(dataset.role_map, sort_keys=True), encoding="utf-8")
    written["role_map"] = rm

    if dataset.column_map:
        cm = out / "column_map.json"
        cm.write_text(
            json.dumps(to_haystack_document(dataset.column_map), indent=2),
            encoding="utf-8",
        )
        written["column_map"] = cm

    for key, filename in (
        ("motor_hours", "motor_hours.csv"),
        ("motor_weekly", "motor_weekly.csv"),
        ("mech_cooling_oat_bins", "mech_cooling_oat_bins.csv"),
        ("mech_cooling_coverage", "mech_cooling_coverage.csv"),
        ("economizer_weather", "economizer_weather.csv"),
        ("operating_signatures", "operating_signatures.csv"),
        ("schedule_inference_table", "schedule_inference_table.csv"),
    ):
        df = analytics.get(key)
        if df is not None and isinstance(df, pd.DataFrame):
            path = out / filename
            df.to_csv(path, index=False)
            written[key] = path

    # Coverage may be missing on older AgentRun.analytics dicts — derive it here
    if "mech_cooling_coverage" not in analytics:
        cov = mech_cooling_coverage(
            dataset.frames,
            dataset.role_map,
            weather=dataset.weather,
            prefer_web_oat=dataset.prefer_web_oat,
        )
        if isinstance(cov, pd.DataFrame) and not cov.empty:
            path = out / "mech_cooling_coverage.csv"
            cov.to_csv(path, index=False)
            written["mech_cooling_coverage"] = path

    # WattLab big dump: sensor stats sliced by operating proof + setpoint medians
    stats_tables = sensor_stats_tables(dataset.frames, dataset.role_map)
    for slice_key, df in stats_tables.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            path = out / f"sensor_stats_{slice_key}.csv"
            df.to_csv(path, index=False)
            written[f"sensor_stats_{slice_key}"] = path

    sp = setpoints_table(dataset.frames, dataset.role_map)
    if isinstance(sp, pd.DataFrame) and not sp.empty:
        path = out / "setpoints.csv"
        sp.to_csv(path, index=False)
        written["setpoints"] = path

    # 24h critical-sensor diurnal profiles (weekday/weekend/holiday × fan state)
    diurnal = diurnal_profiles(dataset.frames, dataset.role_map)
    if isinstance(diurnal, pd.DataFrame) and not diurnal.empty:
        path = out / "sensor_diurnal_24h.csv"
        diurnal.to_csv(path, index=False)
        written["sensor_diurnal_24h"] = path

    # Analytic-tab CSVs (topology, data model, sensor health, RCx comfort, meters)
    try:
        from app.data_model_tree import build_data_model_tree

        tree = build_data_model_tree(
            dataset.frames,
            dataset.role_map,
            building_id=dataset.building_id,
        )
        topo = pd.DataFrame(tree.topology_rows())
        if not topo.empty:
            path = out / "topology.csv"
            topo.to_csv(path, index=False)
            written["topology"] = path
        dm = pd.DataFrame(tree.to_rows())
        if not dm.empty:
            path = out / "data_model.csv"
            dm.to_csv(path, index=False)
            written["data_model"] = path
    except Exception:
        pass

    try:
        from app.analytics import sensor_fault_summary, sensor_health_matrix
        from app.role_map import apply_role_map

        health_rows: list[pd.DataFrame] = []
        fault_rows: list[pd.DataFrame] = []
        for eq_id, raw in dataset.frames.items():
            mapped = apply_role_map(raw, eq_id, dataset.role_map)
            mapped.attrs.update(raw.attrs)
            eq_results = [r for r in (run.results or []) if r.equipment_id == eq_id]
            hm = sensor_health_matrix(mapped, eq_results, equipment_id=eq_id)
            if isinstance(hm, pd.DataFrame) and not hm.empty:
                health_rows.append(hm)
            fs = sensor_fault_summary(mapped, eq_results, equipment_id=eq_id)
            if isinstance(fs, pd.DataFrame) and not fs.empty:
                fault_rows.append(fs)
        if health_rows:
            path = out / "sensor_health_matrix.csv"
            pd.concat(health_rows, ignore_index=True).to_csv(path, index=False)
            written["sensor_health_matrix"] = path
        if fault_rows:
            path = out / "sensor_fault_summary.csv"
            pd.concat(fault_rows, ignore_index=True).to_csv(path, index=False)
            written["sensor_fault_summary"] = path
    except Exception:
        pass

    try:
        from app.occupancy import OccupancySchedule
        from app.rcx_plots import zone_comfort_fail_ranking

        ranking = zone_comfort_fail_ranking(
            dataset.frames,
            dataset.role_map,
            schedule=OccupancySchedule(),
            comfort_low_f=70.0,
            comfort_high_f=75.0,
        )
        if isinstance(ranking, pd.DataFrame) and not ranking.empty:
            path = out / "rcx_zone_comfort_ranking.csv"
            ranking.to_csv(path, index=False)
            written["rcx_zone_comfort_ranking"] = path
    except Exception:
        pass

    try:
        from app.metering import build_meter_monthly_table

        for kind, filename, key in (
            ("electric", "meter_monthly_electric.csv", "meter_monthly_electric"),
            ("gas", "meter_monthly_gas.csv", "meter_monthly_gas"),
        ):
            monthly, _stats, _reason = build_meter_monthly_table(
                dataset.frames,
                dataset.role_map,
                kind=kind,  # type: ignore[arg-type]
                weather=dataset.weather,
            )
            if isinstance(monthly, pd.DataFrame) and not monthly.empty:
                path = out / filename
                monthly.to_csv(path, index=False)
                written[key] = path
    except Exception:
        pass

    written["readme_wattlab"] = write_wattlab_readme(out)

    sched_payload = analytics.get("schedule_inference")
    if isinstance(sched_payload, dict):
        si = out / "schedule_inference.json"
        si.write_text(json.dumps(sched_payload, indent=2, default=str), encoding="utf-8")
        written["schedule_inference"] = si

    # Observed weather for AMY EPW / calibration
    if dataset.weather is not None and isinstance(dataset.weather, pd.DataFrame) and not dataset.weather.empty:
        wx = dataset.weather.copy()
        if isinstance(wx.index, pd.DatetimeIndex):
            wx = wx.reset_index()
            # Normalize timestamp column name
            first = wx.columns[0]
            if first != "timestamp_utc":
                wx = wx.rename(columns={first: "timestamp_utc"})
        wx_path = out / "weather_observed.csv"
        wx.to_csv(wx_path, index=False)
        written["weather_observed"] = wx_path

    if utility_bills:
        bills_path = out / "utility_bills.csv"
        pd.DataFrame(utility_bills).to_csv(bills_path, index=False)
        written["utility_bills"] = bills_path

    seed = build_model_seed_dict(
        building_id=dataset.building_id,
        schedule_payload=sched_payload if isinstance(sched_payload, dict) else {"equipment": {}, "data_window": {}},
        signatures=analytics.get("operating_signatures")
        if isinstance(analytics.get("operating_signatures"), pd.DataFrame)
        else None,
        city=city,
        lat=lat,
        lon=lon,
        utility_bills=utility_bills,
    )
    ms = out / "model_seed.json"
    ms.write_text(json.dumps(seed, indent=2, default=str), encoding="utf-8")
    written["model_seed"] = ms

    if isinstance(rcx, pd.DataFrame):
        path = out / "rcx_preset_coverage.csv"
        rcx.to_csv(path, index=False)
        written["rcx_preset_coverage"] = path

    if include_gap_report and isinstance(gap, pd.DataFrame) and not gap.empty:
        path = out / "role_map_gap_report.csv"
        gap.to_csv(path, index=False)
        written["role_map_gap_report"] = path

    if run.tuning_report:
        path = out / "tuning_assistant_report.json"
        path.write_text(json.dumps(run.tuning_report, indent=2, default=str), encoding="utf-8")
        written["tuning_assistant_report"] = path

    files_suppressed = 0
    if export_counts is not None:
        files_suppressed = int(sum(int(v) for v in export_counts.suppressed_status.values()))

    # Finalize run_report once before measuring. Directory byte/file counts are
    # recorded on MANIFEST under an explicit payload scope (excludes MANIFEST).
    stage_seconds["serialization"] = round(time.perf_counter() - t_serialize, 6)
    report = {
        "building_id": dataset.building_id,
        "source_path": dataset.source_path,
        "package_report": dataset.package_report,
        "package_health": (dataset.package_report or {}).get("package_health"),
        "package_health_grade": (dataset.package_report or {}).get("package_health_grade"),
        "warnings": dataset.warnings,
        "status_counts": status_counts,
        "applicable_count": applicable_count,
        "non_applicable_count": non_applicable_count,
        "result_count": len(results_list),
        "meta": run.meta,
        "tuning_report": run.tuning_report,
        "rule_catalog_count": len(RULES),
        "export_profile": export_profile,
        "files_suppressed": files_suppressed,
        "stage_seconds": {
            "rule_execution": stage_seconds["rule_execution"],
            "analytics": stage_seconds["analytics"],
            "serialization": stage_seconds["serialization"],
            # compression filled on MANIFEST after payload zip timing
            "compression": 0.0,
        },
        "stage_scope": dict(EXPORT_STAGE_SCOPE),
        "metrics_scope": dict(EXPORT_METRICS_SCOPE),
    }
    rp = out / "run_report.json"
    rp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    written["run_report"] = rp

    # Payload metrics after final run_report: all files except MANIFEST.
    payload_paths = [p for p in out.rglob("*") if p.is_file() and p.name != "MANIFEST.json"]
    payload_file_count = len(payload_paths)
    payload_uncompressed_bytes = sum(p.stat().st_size for p in payload_paths)

    t_compress = time.perf_counter()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(payload_paths):
            zf.write(p, arcname=p.relative_to(out).as_posix())
    payload_compressed_bytes = len(buf.getvalue())
    stage_seconds["compression"] = round(time.perf_counter() - t_compress, 6)

    written["manifest"] = write_manifest(
        out,
        written,
        profile=export_profile,
        export_counts=export_counts,
        result_status_counts=status_counts,
        applicable_count=applicable_count,
        non_applicable_count=non_applicable_count,
        files_suppressed=files_suppressed,
        payload_file_count=payload_file_count,
        payload_uncompressed_bytes=payload_uncompressed_bytes,
        payload_compressed_bytes=payload_compressed_bytes,
        package_file_count=payload_file_count + 1,
        metrics_scope=EXPORT_METRICS_SCOPE,
        stage_seconds=stage_seconds,
        stage_scope=EXPORT_STAGE_SCOPE,
    )
    package_file_count = sum(1 for p in out.rglob("*") if p.is_file())
    man_path = out / "MANIFEST.json"
    man_payload = json.loads(man_path.read_text(encoding="utf-8"))
    if man_payload.get("package_file_count") != package_file_count:
        man_payload["package_file_count"] = package_file_count
        man_path.write_text(json.dumps(man_payload, indent=2, default=str), encoding="utf-8")

    # Streamlit bridge: write bootstrap so the next app start auto-loads this run
    if not include_bootstrap:
        return written
    try:
        from app.bootstrap import build_bootstrap_payload, write_bootstrap

        pkg = dataset.source_path if str(dataset.source_path).lower().endswith(".zip") else None
        folder = None if pkg else (dataset.source_path or None)
        # Prefer original zip if source_path is an extract dir but package was zip — use source_path as-is
        src = Path(dataset.source_path) if dataset.source_path else None
        if src and src.is_file() and src.suffix.lower() == ".zip":
            pkg, folder = str(src), None
        elif src and src.is_dir():
            pkg, folder = None, str(src)

        boot = build_bootstrap_payload(
            package_path=pkg,
            building_folder=folder,
            session_config=session,
            fault_settings_path=fs,
            column_map_path=written.get("column_map"),
            out_dir=out,
            auto_run_rules=True,
            notes=f"building_id={dataset.building_id}",
        )
        for bp in write_bootstrap(boot, path=out / "streamlit_bootstrap.json", also_default=True):
            written[f"bootstrap:{bp.name}"] = bp
    except Exception:
        pass  # bootstrap is best-effort; never fail the export

    return written
