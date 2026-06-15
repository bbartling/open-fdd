"""Bench 5007 long-running FDD validation — data-model-driven, source-agnostic."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.confirmation import CONFIRMATION_ENGINE, confirm_fault_mask
from open_fdd.arrow_runtime.datafusion_backend import datafusion_available, run_datafusion_sql_rule
from open_fdd.arrow_runtime.execution_evidence import validate_computation_path

BACNET_SOURCE = "bacnet_direct"
NIAGARA_SOURCE = "niagara_baskstream"
HISTORIAN_SOURCE_MAP = {
    BACNET_SOURCE: "bacnet",
    NIAGARA_SOURCE: "niagara_baskstream",
}
DEFAULT_SEMANTICS = ("duct-t", "oa-t", "stat_zn-t", "oa-h")
TIMESTAMP_COL = "timestamp"


@dataclass
class SmokeConfig:
    site_id: str = "demo"
    bacnet_device_id: int = 5007
    niagara_station: str = "bench9065"
    duration_minutes: int = 120
    poll_seconds: int = 60
    baseline_minutes: int = 20
    confirmation_minutes: float = 10.0
    confirmation_rows: int = 10
    primary_semantic: str = "duct-t"
    fault_direction: str = "below"
    forced_threshold_f: float = 80.0
    baseline_threshold_f: float = -100.0
    overnight: bool = False
    dry_run: bool = False
    synthetic: bool = False
    strict_datafusion: bool = False
    align_tolerance_s: int = 90
    secondary_semantics: tuple[str, ...] = DEFAULT_SEMANTICS
    base_url: str = "http://127.0.0.1:8765"
    reports_dir: str = "workspace/reports"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> SmokeConfig:
        import os

        e = env or os.environ
        overnight = e.get("OPENFDD_SMOKE_OVERNIGHT", "").strip().lower() in ("1", "true", "yes")
        duration = int(e.get("OPENFDD_SMOKE_DURATION_MINUTES", "720" if overnight else "120"))
        return cls(
            site_id=e.get("OPENFDD_SMOKE_SITE_ID", "demo"),
            bacnet_device_id=int(e.get("OPENFDD_SMOKE_BACNET_DEVICE_ID", "5007")),
            niagara_station=e.get("OPENFDD_SMOKE_NIAGARA_STATION", "bench9065"),
            duration_minutes=duration,
            poll_seconds=int(e.get("OPENFDD_SMOKE_POLL_SECONDS", "60")),
            baseline_minutes=int(e.get("OPENFDD_SMOKE_BASELINE_MINUTES", "20")),
            confirmation_minutes=float(e.get("OPENFDD_SMOKE_CONFIRMATION_MINUTES", "10")),
            confirmation_rows=int(e.get("OPENFDD_SMOKE_CONFIRMATION_ROWS", "10")),
            primary_semantic=e.get("OPENFDD_SMOKE_PRIMARY_SEMANTIC", "duct-t"),
            fault_direction=e.get("OPENFDD_SMOKE_FAULT_DIRECTION", "below"),
            forced_threshold_f=float(e.get("OPENFDD_SMOKE_FORCED_THRESHOLD_F", "80.0")),
            overnight=overnight,
            base_url=e.get("OPENFDD_BASE_URL", "http://127.0.0.1:8765"),
            reports_dir=e.get("OPENFDD_SMOKE_REPORTS_DIR", "workspace/reports"),
        )


@dataclass
class PointAlignment:
    semantic_key: str
    source: str
    point_id: str
    equipment_id: str
    historian_column: str
    brick_type: str
    fdd_input: str
    units: str = ""


@dataclass
class FddRunMetrics:
    source: str
    point_id: str
    equipment_id: str
    semantic_key: str
    backend: str
    row_count: int = 0
    raw_true_count: int = 0
    confirmed_true_count: int = 0
    false_count: int = 0
    null_count: int = 0
    first_sample_time: str = ""
    last_sample_time: str = ""
    first_raw_fault_time: str = ""
    first_confirmed_fault_time: str = ""
    confirmation_delay_seconds: float | None = None
    expected_confirmation_delay_seconds: float = 0.0
    mismatch_count: int = 0
    rule_hash: str = ""
    rule_config: dict[str, Any] = field(default_factory=dict)
    execution_evidence: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class EquivalenceResult:
    comparison: str
    rows_aligned: int = 0
    mismatches: int = 0
    first_mismatch_timestamp: str = ""
    value_delta_avg: float | None = None
    value_delta_max: float | None = None
    pass_: bool = True
    notes: str = ""


@dataclass
class SmokeEvent:
    timestamp: str
    event_type: str
    source: str = ""
    backend: str = ""
    point_id: str = ""
    semantic_key: str = ""
    value: float | None = None
    raw_fault: bool | None = None
    confirmed_fault: bool | None = None
    streak_rows: int | None = None
    elapsed_seconds: float | None = None
    message: str = ""


@dataclass
class ValidationReport:
    config: SmokeConfig
    verdict: str = "FAIL"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    model_alignment: list[PointAlignment] = field(default_factory=list)
    polling_health: list[dict[str, Any]] = field(default_factory=list)
    rule_config: dict[str, Any] = field(default_factory=dict)
    execution_evidence: list[dict[str, Any]] = field(default_factory=list)
    fault_timeline: list[FddRunMetrics] = field(default_factory=list)
    matrix_runs: list[FddRunMetrics] = field(default_factory=list)
    backend_equivalence: list[EquivalenceResult] = field(default_factory=list)
    source_equivalence: list[EquivalenceResult] = field(default_factory=list)
    events: list[SmokeEvent] = field(default_factory=list)
    hourly_rollups: list[dict[str, Any]] = field(default_factory=list)
    threshold_change_at: str = ""
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        def _conv(obj: Any) -> Any:
            if hasattr(obj, "__dataclass_fields__"):
                d = asdict(obj)
                if "pass_" in d:
                    d["pass"] = d.pop("pass_")
                return d
            if isinstance(obj, list):
                return [_conv(x) for x in obj]
            return obj

        return _conv(self)


TableLoader = Callable[[str, str, list[str]], tuple[pa.Table | None, str]]


def historian_source(metadata_source: str) -> str:
    return HISTORIAN_SOURCE_MAP.get(metadata_source, metadata_source)


def plot_column_name(point: dict[str, Any]) -> str:
    ext = str(point.get("external_id") or "").strip()
    fdd = str(point.get("fdd_input") or "").strip()
    return ext or fdd or str(point.get("id") or "")


def align_semantic_points(model: dict[str, Any], site_id: str) -> dict[str, dict[str, PointAlignment]]:
    """Index paired sensors by cross_source_semantic and metadata.source."""
    out: dict[str, dict[str, PointAlignment]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") != site_id:
            continue
        meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
        semantic = str(meta.get("cross_source_semantic") or pt.get("fdd_input") or "").strip()
        source = str(meta.get("source") or "").strip()
        if not semantic or not source:
            continue
        out.setdefault(semantic, {})[source] = PointAlignment(
            semantic_key=semantic,
            source=source,
            point_id=str(pt.get("id") or ""),
            equipment_id=str(pt.get("equipment_id") or ""),
            historian_column=plot_column_name(pt),
            brick_type=str(pt.get("brick_type") or ""),
            fdd_input=str(pt.get("fdd_input") or semantic),
            units=str(pt.get("units") or ""),
        )
    return out


def validate_model_preflight(model: dict[str, Any], cfg: SmokeConfig) -> list[str]:
    errors: list[str] = []
    sites = {str(s.get("id")) for s in model.get("sites") or [] if isinstance(s, dict)}
    if cfg.site_id not in sites:
        errors.append(f"site {cfg.site_id!r} missing from commissioning model")
    equip = {str(e.get("id")) for e in model.get("equipment") or [] if isinstance(e, dict)}
    for eid in ("bacnet-5007", "niagara-bench9065"):
        if eid not in equip:
            errors.append(f"equipment {eid!r} missing from model")
    aligned = align_semantic_points(model, cfg.site_id)
    primary = aligned.get(cfg.primary_semantic) or {}
    if BACNET_SOURCE not in primary:
        errors.append(f"BACnet paired point missing for semantic {cfg.primary_semantic!r}")
    if NIAGARA_SOURCE not in primary:
        errors.append(f"Niagara paired point missing for semantic {cfg.primary_semantic!r}")
    return errors


def _sql_quote_column(name: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return f'"{name}"'


def build_pyarrow_threshold_code(value_column: str, *, direction: str = "below") -> str:
    col = repr(value_column)
    op = "pc.less" if direction == "below" else "pc.greater"
    return f'''import pyarrow as pa
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    threshold = float((cfg or {{}}).get("threshold") or 80.0)
    col = {col}
    if col not in table.column_names:
        return pa.array([False] * table.num_rows, type=pa.bool_())
    vals = pc.cast(table[col], "float64")
    return {op}(vals, threshold)
'''


def build_datafusion_threshold_sql(value_column: str, threshold: float, *, direction: str = "below") -> str:
    col = _sql_quote_column(value_column)
    op = "<" if direction == "below" else ">"
    return f"SELECT *, {col} {op} {float(threshold)} AS fault FROM telemetry"


def rule_config_snapshot(
    cfg: SmokeConfig,
    *,
    threshold: float,
    value_column: str,
    phase: str,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "threshold": threshold,
        "value_column": value_column,
        "fault_direction": cfg.fault_direction,
        "min_true_rows": cfg.confirmation_rows,
        "min_elapsed_minutes": cfg.confirmation_minutes,
        "poll_interval_s": cfg.poll_seconds,
        "timestamp_column": TIMESTAMP_COL,
    }


def _rule_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _mask_true_count(mask: pa.Array | pa.ChunkedArray) -> int:
    return int(pc.sum(pc.cast(mask, pa.int64())).as_py() or 0)


def evaluate_backend_on_table(
    table: pa.Table,
    *,
    alignment: PointAlignment,
    backend: str,
    cfg: SmokeConfig,
    threshold: float,
    phase: str,
    include_raw: bool = True,
) -> FddRunMetrics:
    value_col = alignment.fdd_input if alignment.fdd_input in table.column_names else alignment.historian_column
    if value_col not in table.column_names and alignment.semantic_key in table.column_names:
        value_col = alignment.semantic_key

    rule_cfg = rule_config_snapshot(cfg, threshold=threshold, value_column=value_col, phase=phase)
    arrow_code = build_pyarrow_threshold_code(value_col, direction=cfg.fault_direction)
    sql = build_datafusion_threshold_sql(value_col, threshold, direction=cfg.fault_direction)

    metrics = FddRunMetrics(
        source=alignment.source,
        point_id=alignment.point_id,
        equipment_id=alignment.equipment_id,
        semantic_key=alignment.semantic_key,
        backend=backend,
        rule_config=rule_cfg,
        expected_confirmation_delay_seconds=cfg.confirmation_minutes * 60.0,
    )

    if table.num_rows == 0:
        metrics.errors.append("empty historian table")
        return metrics

    ts_col = table.column(TIMESTAMP_COL) if TIMESTAMP_COL in table.column_names else None
    if ts_col is not None:
        metrics.first_sample_time = str(ts_col[0].as_py())
        metrics.last_sample_time = str(ts_col[-1].as_py())

    try:
        if backend == "pyarrow":
            raw_cfg = {k: v for k, v in rule_cfg.items() if k not in ("min_true_rows", "min_elapsed_minutes")}
            raw_res = run_arrow_rule(arrow_code, table, raw_cfg, rule_id=f"smoke-{alignment.semantic_key}-raw")
            if raw_res.errors:
                metrics.errors.extend(raw_res.errors)
                return metrics
            conf_res = run_arrow_rule(arrow_code, table, rule_cfg, rule_id=f"smoke-{alignment.semantic_key}")
            if conf_res.errors:
                metrics.errors.extend(conf_res.errors)
                return metrics
            raw_mask = raw_res.fault_mask
            conf_mask = conf_res.fault_mask
            evidence = conf_res.summary.get("execution_evidence") or {}
            metrics.rule_hash = _rule_hash(arrow_code)
            result = conf_res
        elif backend == "datafusion_sql":
            if not datafusion_available():
                metrics.errors.append("DataFusion not installed")
                return metrics
            raw_cfg = {k: v for k, v in rule_cfg.items() if k not in ("min_true_rows", "min_elapsed_minutes")}
            raw_res = run_datafusion_sql_rule(sql, table, raw_cfg, rule_id=f"smoke-sql-{alignment.semantic_key}-raw")
            conf_res = run_datafusion_sql_rule(sql, table, rule_cfg, rule_id=f"smoke-sql-{alignment.semantic_key}")
            if conf_res.errors:
                metrics.errors.extend(conf_res.errors)
                return metrics
            raw_mask = raw_res.fault_mask
            conf_mask = conf_res.fault_mask
            evidence = conf_res.summary.get("execution_evidence") or {}
            metrics.rule_hash = _rule_hash(sql)
            result = conf_res
        else:
            metrics.errors.append(f"unknown backend {backend!r}")
            return metrics
    except Exception as exc:  # noqa: BLE001
        metrics.errors.append(str(exc))
        return metrics

    metrics.row_count = result.row_count
    metrics.raw_true_count = _mask_true_count(raw_mask)
    metrics.confirmed_true_count = _mask_true_count(conf_mask)
    metrics.false_count = result.false_count
    metrics.null_count = result.null_count
    metrics.execution_evidence = evidence
    metrics.errors.extend(validate_computation_path(evidence))

    if ts_col is not None:
        metrics.first_raw_fault_time = _first_true_timestamp(ts_col, raw_mask)
        metrics.first_confirmed_fault_time = _first_true_timestamp(ts_col, conf_mask)
        if metrics.first_raw_fault_time and metrics.first_confirmed_fault_time:
            t0 = _parse_ts(metrics.first_raw_fault_time)
            t1 = _parse_ts(metrics.first_confirmed_fault_time)
            if t0 and t1:
                metrics.confirmation_delay_seconds = (t1 - t0).total_seconds()

    return metrics


def _parse_ts(value: str) -> datetime | None:
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _first_true_timestamp(timestamps: pa.Array | pa.ChunkedArray, mask: pa.Array | pa.ChunkedArray) -> str:
    """Report serialization — allowed to use Python iteration after Arrow computation."""
    ts_list = timestamps.to_pylist()
    mask_list = mask.to_pylist()
    for ts, val in zip(ts_list, mask_list):
        if val is True:
            return str(ts)
    return ""


def compare_masks_arrow(
    left: pa.Array | pa.ChunkedArray,
    right: pa.Array | pa.ChunkedArray,
) -> tuple[int, int]:
    equal_raw = pc.equal(left, right)
    both_null = pc.and_(pc.is_null(left), pc.is_null(right))
    equal = pc.fill_null(pc.or_(pc.fill_null(equal_raw, False), both_null), False)
    mismatch = pc.invert(equal)
    mismatch_count = int(pc.sum(pc.cast(mismatch, pa.int64())).as_py() or 0)
    matching = len(left) - mismatch_count
    return matching, mismatch_count


def compare_backend_equivalence(
    left: FddRunMetrics,
    right: FddRunMetrics,
    *,
    mask_left: pa.Array | pa.ChunkedArray,
    mask_right: pa.Array | pa.ChunkedArray,
    label: str,
) -> EquivalenceResult:
    aligned, mismatches = compare_masks_arrow(mask_left, mask_right)
    return EquivalenceResult(
        comparison=label,
        rows_aligned=aligned,
        mismatches=mismatches,
        pass_=mismatches == 0 and not left.errors and not right.errors,
        notes="; ".join(left.errors + right.errors),
    )


def build_synthetic_dual_tables(
    cfg: SmokeConfig,
    *,
    total_rows: int,
    baseline_rows: int,
    baseline_value: float = 90.0,
    fault_value: float = 75.0,
) -> dict[str, pa.Table]:
    """BACnet-like and Niagara-like tables with same semantic values, separate source metadata."""
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    timestamps: list[str] = []
    values: list[float] = []
    for i in range(total_rows):
        timestamps.append((start + timedelta(seconds=i * cfg.poll_seconds)).isoformat().replace("+00:00", "Z"))
        values.append(baseline_value if i < baseline_rows else fault_value)

    aligned = {
        BACNET_SOURCE: pa.table(
            {
                TIMESTAMP_COL: timestamps,
                "site_id": [cfg.site_id] * total_rows,
                "duct-t": values,
                "oa-t": values,
                "stat_zn-t": values,
                "oa-h": [50.0] * total_rows,
                "equipment_id": ["bacnet-5007"] * total_rows,
                "metadata.source": [BACNET_SOURCE] * total_rows,
            }
        ),
        NIAGARA_SOURCE: pa.table(
            {
                TIMESTAMP_COL: timestamps,
                "site_id": [cfg.site_id] * total_rows,
                "duct-t": values,
                "oa-t": values,
                "stat_zn-t": values,
                "oa-h": [50.0] * total_rows,
                "equipment_id": ["niagara-bench9065"] * total_rows,
                "metadata.source": [NIAGARA_SOURCE] * total_rows,
            }
        ),
    }
    return aligned


def validate_confirmation_timing(
    table: pa.Table,
    *,
    cfg: SmokeConfig,
    threshold: float,
    baseline_rows: int,
) -> list[str]:
    """Unit-test helper: assert fault confirmation window semantics on synthetic data."""
    errors: list[str] = []
    alignment = PointAlignment(
        semantic_key=cfg.primary_semantic,
        source=BACNET_SOURCE,
        point_id="synthetic",
        equipment_id="bacnet-5007",
        historian_column=cfg.primary_semantic,
        brick_type="Discharge_Air_Temperature_Sensor",
        fdd_input=cfg.primary_semantic,
    )
    metrics = evaluate_backend_on_table(
        table,
        alignment=alignment,
        backend="pyarrow",
        cfg=cfg,
        threshold=threshold,
        phase="fault",
    )
    if metrics.errors:
        return metrics.errors

    # Before confirmation window: first baseline_rows should have no confirmed fault at end of baseline
    baseline_table = table.slice(0, baseline_rows)
    base_metrics = evaluate_backend_on_table(
        baseline_table,
        alignment=alignment,
        backend="pyarrow",
        cfg=cfg,
        threshold=threshold,
        phase="baseline",
    )
    if base_metrics.confirmed_true_count > 0:
        errors.append("confirmed fault during baseline slice")

    # Before fault confirmation window ends: early post-change slice should not confirm
    post_change = table.slice(baseline_rows, cfg.confirmation_rows - 1)
    if post_change.num_rows > 0:
        early = evaluate_backend_on_table(
            post_change,
            alignment=alignment,
            backend="pyarrow",
            cfg=cfg,
            threshold=threshold,
            phase="fault-early",
        )
        if early.confirmed_true_count > 0:
            errors.append("confirmed fault before fault confirmation window elapsed")

    if metrics.confirmed_true_count < 1:
        errors.append("expected confirmed fault after fault confirmation window")

    # DataFusion parity
    if datafusion_available():
        df_metrics = evaluate_backend_on_table(
            table,
            alignment=alignment,
            backend="datafusion_sql",
            cfg=cfg,
            threshold=threshold,
            phase="fault",
        )
        if df_metrics.confirmed_true_count != metrics.confirmed_true_count:
            errors.append(
                f"PyArrow/DataFusion confirmed count mismatch: "
                f"{metrics.confirmed_true_count} vs {df_metrics.confirmed_true_count}"
            )
    return errors


def run_synthetic_validation(cfg: SmokeConfig, model: dict[str, Any] | None = None) -> ValidationReport:
    report = ValidationReport(
        config=cfg,
        started_at=datetime.now(timezone.utc).isoformat(),
        environment={"mode": "synthetic", "datafusion_installed": datafusion_available()},
    )
    if model is None:
        model = json.loads((Path(__file__).resolve().parents[2] / "workspace/data/bench_dual_source_model.json").read_text())

    report.errors.extend(validate_model_preflight(model, cfg))
    aligned = align_semantic_points(model, cfg.site_id)
    for semantic, by_source in aligned.items():
        for pt in by_source.values():
            report.model_alignment.append(pt)

    baseline_rows = max(1, int(round(cfg.baseline_minutes * 60 / cfg.poll_seconds)))
    total_rows = max(
        baseline_rows + cfg.confirmation_rows + 5,
        int(round(cfg.duration_minutes * 60 / cfg.poll_seconds)),
    )
    if cfg.dry_run:
        total_rows = baseline_rows + cfg.confirmation_rows + 2
        cfg = SmokeConfig(**{**asdict(cfg), "duration_minutes": max(1, int(total_rows * cfg.poll_seconds / 60))})

    tables = build_synthetic_dual_tables(cfg, total_rows=total_rows, baseline_rows=baseline_rows)
    report.threshold_change_at = tables[BACNET_SOURCE].column(TIMESTAMP_COL)[baseline_rows].as_py()

    report.rule_config = rule_config_snapshot(
        cfg,
        threshold=cfg.forced_threshold_f,
        value_column=cfg.primary_semantic,
        phase="fault",
    )

    backends = ("pyarrow", "datafusion_sql")
    masks: dict[tuple[str, str], pa.Array | pa.ChunkedArray] = {}
    for source in (BACNET_SOURCE, NIAGARA_SOURCE):
        table = tables[source]
        pt = aligned[cfg.primary_semantic][source]
        for backend in backends:
            if backend == "datafusion_sql" and not datafusion_available():
                report.warnings.append("DataFusion not installed — SQL backend skipped")
                continue
            m = evaluate_backend_on_table(
                table,
                alignment=pt,
                backend=backend,
                cfg=cfg,
                threshold=cfg.forced_threshold_f,
                phase="fault",
            )
            report.matrix_runs.append(m)
            report.execution_evidence.append({"run": f"{source}/{backend}", **m.execution_evidence})
            if m.execution_evidence.get("confirmation_engine") == CONFIRMATION_ENGINE:
                report.warnings.append(
                    f"confirmation_engine={CONFIRMATION_ENGINE} for {source}/{backend} (expected until vectorized)"
                )
            # stash masks for equivalence — re-run for mask access
            if backend == "pyarrow":
                res = run_arrow_rule(
                    build_pyarrow_threshold_code(pt.fdd_input, direction=cfg.fault_direction),
                    table,
                    rule_config_snapshot(cfg, threshold=cfg.forced_threshold_f, value_column=pt.fdd_input, phase="fault"),
                )
            else:
                res = run_datafusion_sql_rule(
                    build_datafusion_threshold_sql(pt.fdd_input, cfg.forced_threshold_f, direction=cfg.fault_direction),
                    table,
                    rule_config_snapshot(cfg, threshold=cfg.forced_threshold_f, value_column=pt.fdd_input, phase="fault"),
                )
            masks[(source, backend)] = res.fault_mask
            report.fault_timeline.append(m)

    # Baseline: no confirmed fault with safe threshold
    base_table = tables[BACNET_SOURCE].slice(0, baseline_rows)
    base_pt = aligned[cfg.primary_semantic][BACNET_SOURCE]
    base_m = evaluate_backend_on_table(
        base_table,
        alignment=base_pt,
        backend="pyarrow",
        cfg=cfg,
        threshold=cfg.baseline_threshold_f,
        phase="baseline",
    )
    if base_m.confirmed_true_count > 0:
        report.errors.append("baseline confirmed fault unexpected")

    timing_errors = validate_confirmation_timing(
        tables[BACNET_SOURCE],
        cfg=cfg,
        threshold=cfg.forced_threshold_f,
        baseline_rows=baseline_rows,
    )
    report.errors.extend(timing_errors)

    # Backend equivalence on BACnet
    if (BACNET_SOURCE, "pyarrow") in masks and (BACNET_SOURCE, "datafusion_sql") in masks:
        py_m = next(r for r in report.matrix_runs if r.source == BACNET_SOURCE and r.backend == "pyarrow")
        df_m = next(r for r in report.matrix_runs if r.source == BACNET_SOURCE and r.backend == "datafusion_sql")
        report.backend_equivalence.append(
            compare_backend_equivalence(
                py_m,
                df_m,
                mask_left=masks[(BACNET_SOURCE, "pyarrow")],
                mask_right=masks[(BACNET_SOURCE, "datafusion_sql")],
                label="BACnet PyArrow vs DataFusion SQL",
            )
        )

    # Source equivalence PyArrow
    if (BACNET_SOURCE, "pyarrow") in masks and (NIAGARA_SOURCE, "pyarrow") in masks:
        b_m = next(r for r in report.matrix_runs if r.source == BACNET_SOURCE and r.backend == "pyarrow")
        n_m = next(r for r in report.matrix_runs if r.source == NIAGARA_SOURCE and r.backend == "pyarrow")
        report.source_equivalence.append(
            compare_backend_equivalence(
                b_m,
                n_m,
                mask_left=masks[(BACNET_SOURCE, "pyarrow")],
                mask_right=masks[(NIAGARA_SOURCE, "pyarrow")],
                label="BACnet vs Niagara (PyArrow)",
            )
        )

    report.events.append(
        SmokeEvent(
            timestamp=report.threshold_change_at,
            event_type="threshold_change",
            semantic_key=cfg.primary_semantic,
            message=f"forced threshold {cfg.forced_threshold_f}F ({cfg.fault_direction})",
        )
    )

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.verdict = _compute_verdict(report)
    return report


def _compute_verdict(report: ValidationReport) -> str:
    if report.errors:
        return "FAIL"
    hard_fails = [e for e in report.execution_evidence if e.get("computation_path") == "python_list"]
    if hard_fails:
        return "FAIL"
    equiv_fail = [e for e in report.backend_equivalence + report.source_equivalence if not e.pass_]
    if equiv_fail:
        return "FAIL"
    if report.warnings:
        return "WARN"
    return "PASS"


def write_report_artifacts(report: ValidationReport, reports_dir: Path) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = reports_dir / f"bench_5007_long_fdd_{stamp}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    csv_path = Path(str(base) + "_events.csv")

    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    csv_path.write_text(render_events_csv(report), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path), "csv": str(csv_path)}


def render_events_csv(report: ValidationReport) -> str:
    header = (
        "timestamp,event_type,source,backend,point_id,semantic_key,value,raw_fault,confirmed_fault,"
        "streak_rows,elapsed_seconds,message\n"
    )
    lines = [header]
    for ev in report.events:
        lines.append(
            ",".join(
                [
                    _csv(ev.timestamp),
                    _csv(ev.event_type),
                    _csv(ev.source),
                    _csv(ev.backend),
                    _csv(ev.point_id),
                    _csv(ev.semantic_key),
                    _csv(ev.value),
                    _csv(ev.raw_fault),
                    _csv(ev.confirmed_fault),
                    _csv(ev.streak_rows),
                    _csv(ev.elapsed_seconds),
                    _csv(ev.message),
                ]
            )
            + "\n"
        )
    return "".join(lines)


def _csv(val: Any) -> str:
    if val is None:
        return ""
    text = str(val)
    if "," in text or '"' in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def render_markdown_report(report: ValidationReport) -> str:
    cfg = report.config
    lines = [
        "# Bench 5007 Long FDD Smoke Report",
        "",
        "## Summary",
        "",
        f"- **Verdict:** {report.verdict}",
        f"- **Duration:** {cfg.duration_minutes} min",
        f"- **Poll interval:** {cfg.poll_seconds}s",
        f"- **Fault confirmation window:** {cfg.confirmation_rows} rows / {cfg.confirmation_minutes} min "
        f"(at {cfg.poll_seconds}s polling ≈ {cfg.confirmation_rows * cfg.poll_seconds // 60} min)",
        f"- **Started:** {report.started_at}",
        f"- **Finished:** {report.finished_at}",
        "",
        "## Environment",
        "",
        f"- **Site:** {cfg.site_id}",
        f"- **BACnet device:** {cfg.bacnet_device_id}",
        f"- **Niagara station:** {cfg.niagara_station}",
        f"- **DataFusion installed:** {report.environment.get('datafusion_installed', datafusion_available())}",
        "",
        "## Data Model Alignment",
        "",
        "| semantic | source | point_id | historian_column | brick_type | fdd_input |",
        "|---|---|---|---|---|---|",
    ]
    for pt in report.model_alignment:
        lines.append(
            f"| {pt.semantic_key} | {pt.source} | {pt.point_id} | {pt.historian_column} | "
            f"{pt.brick_type} | {pt.fdd_input} |"
        )

    lines.extend(["", "## Rule Configuration", "", "```json", json.dumps(report.rule_config, indent=2), "```"])

    lines.extend(["", "## Arrow/DataFusion Execution Evidence", ""])
    lines.append("| backend | computation_path | confirmation_engine | rows | chunks |")
    lines.append("|---|---|---|---|---|")
    for ev in report.execution_evidence:
        lines.append(
            f"| {ev.get('backend', '')} | {ev.get('computation_path', '')} | "
            f"{ev.get('confirmation_engine', '')} | {ev.get('arrow_num_rows', '')} | "
            f"{ev.get('arrow_chunk_count', '')} |"
        )

    lines.extend(["", "## Fault Timeline", ""])
    lines.append("| source | backend | first_raw_fault | first_confirmed_fault | delay_s | expected_s |")
    lines.append("|---|---|---|---|---|---|")
    for m in report.fault_timeline:
        lines.append(
            f"| {m.source} | {m.backend} | {m.first_raw_fault_time} | {m.first_confirmed_fault_time} | "
            f"{m.confirmation_delay_seconds} | {m.expected_confirmation_delay_seconds} |"
        )

    lines.extend(["", "## Backend Equivalence", ""])
    for eq in report.backend_equivalence:
        lines.append(f"- **{eq.comparison}:** mismatches={eq.mismatches} pass={eq.pass_}")

    lines.extend(["", "## Source Equivalence", ""])
    for eq in report.source_equivalence:
        lines.append(f"- **{eq.comparison}:** mismatches={eq.mismatches} pass={eq.pass_}")

    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        for w in report.warnings:
            lines.append(f"- {w}")

    if report.errors:
        lines.extend(["", "## Errors", ""])
        for err in report.errors:
            lines.append(f"- {err}")

    lines.extend(["", "## Final Verdict", "", f"**{report.verdict}**", ""])
    return "\n".join(lines) + "\n"
