"""Evidence collector interfaces and adapters for graph-based HVAC RCA.

Collects three kinds of node-level evidence (all computations in SI):
1. Rule results / fault episodes (from Open-FDD ``fdd.rule_result``, long-format SQL
   output, CSV/DataFrame, or ``open-fdd-ml confidence`` episode records).
2. Data-quality flags (stale, gap, clipping, ``NOT_ASSESSED`` / untrusted input).
3. Key SI point deviations (e.g. SAT error in K, zone temp error in K, valve saturation).
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol


def parse_utc(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or datetime into timezone-aware UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _opt_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _range_overlaps(
    ev_start: datetime | None,
    ev_end: datetime | None,
    window_start: datetime | None,
    window_end: datetime | None,
    *,
    tolerance: timedelta = timedelta(minutes=30),
) -> bool:
    """True when evidence overlaps the query window.

    Undated evidence always matches. Query bounds are applied independently, so an
    open start or open end still filters against the known side (plus tolerance).
    """
    if ev_start is None and ev_end is None:
        return True
    if window_start is None and window_end is None:
        return True
    ev_s = ev_start if ev_start is not None else ev_end
    ev_e = ev_end if ev_end is not None else ev_start
    if ev_s is None or ev_e is None:
        return True
    if window_start is not None and ev_e < (window_start - tolerance):
        return False
    return window_end is None or ev_s <= (window_end + tolerance)


@dataclass(frozen=True)
class FaultEvidence:
    """A fault episode or active rule failure on an equipment node."""

    equipment_id: str
    rule_id: str
    status: str = "FAULT"
    start: datetime | None = None
    end: datetime | None = None
    p_real: float | None = None
    p_false_positive: float | None = None
    p_tuning: float | None = None
    confidence_label: str | None = None
    is_data_quality: bool = False
    site_id: str = ""
    reason: str = ""

    def overlaps(
        self,
        window_start: datetime | None,
        window_end: datetime | None,
        *,
        tolerance: timedelta = timedelta(minutes=30),
    ) -> bool:
        """True when this fault overlaps the query window (bounds applied independently)."""
        return _range_overlaps(self.start, self.end, window_start, window_end, tolerance=tolerance)


@dataclass(frozen=True)
class DataQualityEvidence:
    """Data-quality or trust warning on a node or its sensor inputs."""

    equipment_id: str
    flag: str
    point_id: str = ""
    detail: str = ""
    site_id: str = ""
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class PointDeviation:
    """Key SI point observation / deviation on an equipment node."""

    equipment_id: str
    role: str
    value_si: float
    setpoint_si: float | None = None
    deviation_si: float | None = None
    unit: str = ""
    timestamp: datetime | None = None
    site_id: str = ""

    @property
    def resolved_deviation_si(self) -> float | None:
        if self.deviation_si is not None:
            return self.deviation_si
        if self.setpoint_si is not None:
            return self.value_si - self.setpoint_si
        return None


@dataclass
class NodeEvidence:
    """All collected RCA evidence for one equipment node within a symptom window."""

    equipment_id: str
    faults: list[FaultEvidence] = field(default_factory=list)
    data_quality_flags: list[DataQualityEvidence] = field(default_factory=list)
    point_deviations: list[PointDeviation] = field(default_factory=list)


class EvidenceCollector(Protocol):
    """Interface for querying fault, data-quality, and SI point-deviation evidence."""

    def all_faults(self) -> list[FaultEvidence]:
        """Return all candidate symptom/node fault records available to this collector."""

    def collect(
        self,
        equipment_id: str,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        site_id: str = "",
        tolerance: timedelta = timedelta(minutes=30),
    ) -> NodeEvidence:
        """Collect overlapping faults, data-quality flags, and SI deviations for ``equipment_id``."""


class InMemoryEvidenceCollector:
    """In-memory ``EvidenceCollector`` backed by fault, data-quality, and deviation lists."""

    def __init__(
        self,
        faults: Iterable[FaultEvidence] = (),
        data_quality_flags: Iterable[DataQualityEvidence] = (),
        point_deviations: Iterable[PointDeviation] = (),
    ) -> None:
        self._faults = list(faults)
        self._dq = list(data_quality_flags)
        self._devs = list(point_deviations)

    def all_faults(self) -> list[FaultEvidence]:
        return list(self._faults)

    def all_data_quality(self) -> list[DataQualityEvidence]:
        return list(self._dq)

    def all_deviations(self) -> list[PointDeviation]:
        return list(self._devs)

    def collect(
        self,
        equipment_id: str,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        site_id: str = "",
        tolerance: timedelta = timedelta(minutes=30),
    ) -> NodeEvidence:
        eq_low = equipment_id.lower()

        def match_site(item_site: str) -> bool:
            return not site_id or not item_site or item_site == site_id

        faults = [
            f
            for f in self._faults
            if f.equipment_id.lower() == eq_low
            and match_site(f.site_id)
            and f.overlaps(window_start, window_end, tolerance=tolerance)
        ]
        dq = [
            d
            for d in self._dq
            if d.equipment_id.lower() == eq_low
            and match_site(d.site_id)
            and _range_overlaps(d.start, d.end, window_start, window_end, tolerance=tolerance)
        ]
        devs = [
            p
            for p in self._devs
            if p.equipment_id.lower() == eq_low
            and match_site(p.site_id)
            and _range_overlaps(p.timestamp, p.timestamp, window_start, window_end, tolerance=tolerance)
        ]
        return NodeEvidence(equipment_id=equipment_id, faults=faults, data_quality_flags=dq, point_deviations=devs)


class DataFrameEvidenceCollector(InMemoryEvidenceCollector):
    """Build RCA evidence from Open-FDD DataFrames, CSVs, or ``open-fdd-ml confidence`` outputs."""

    @classmethod
    def from_rule_results(
        cls,
        results: Any,
        *,
        deviations: Any = None,
        data_quality: Any = None,
        fault_statuses: tuple[str, ...] = ("FAULT", "1", "TRUE"),
    ) -> DataFrameEvidenceCollector:
        """Ingest a DataFrame (or list of dicts) in ``fdd.rule_result`` or long ``flags`` layout."""
        rows = results.to_dict("records") if hasattr(results, "to_dict") else list(results)
        want_status = {s.upper() for s in fault_statuses}
        faults: list[FaultEvidence] = []

        # Support both episode/window rows (window_start/start + status) and sample-level flag rows (timestamp + flag)
        sample_rows: list[dict[str, Any]] = []
        for r in rows:
            if "flag" in r and "timestamp" in r and "window_start" not in r and "start" not in r:
                sample_rows.append(r)
                continue
            status = str(r.get("status", "FAULT")).strip().upper()
            if status not in want_status:
                continue
            faults.append(
                FaultEvidence(
                    equipment_id=str(r["equipment_id"]),
                    rule_id=str(r["rule_id"]),
                    status=status,
                    start=parse_utc(r.get("window_start") or r.get("start")),
                    end=parse_utc(r.get("window_end") or r.get("end")),
                    p_real=_opt_float(r.get("p_real")),
                    p_false_positive=_opt_float(r.get("p_false_positive")),
                    p_tuning=_opt_float(r.get("p_tuning")),
                    confidence_label=r.get("label") or r.get("confidence_label") or None,
                    is_data_quality=_opt_bool(r.get("data_quality_rule") or r.get("is_data_quality")),
                    site_id=str(r.get("site_id") or ""),
                    reason=str(r.get("reason") or ""),
                )
            )

        if sample_rows:
            faults.extend(_episodes_from_sample_rows(sample_rows, want_status))

        dq_items = _parse_dq_rows(data_quality)
        dev_items = _parse_deviation_rows(deviations)
        return cls(faults=faults, data_quality_flags=dq_items, point_deviations=dev_items)

    @classmethod
    def from_confidence_episodes(
        cls,
        source: Path | str | Iterable[Mapping[str, Any]],
        *,
        deviations: Any = None,
        data_quality: Any = None,
    ) -> DataFrameEvidenceCollector:
        """Ingest ``episodes.jsonl``, ``episodes.csv``, or ``report.json`` from ``open-fdd-ml confidence``."""
        records: list[Mapping[str, Any]] = []
        if isinstance(source, (Path, str)):
            path = Path(source)
            suffix = path.suffix.lower()
            if suffix == ".jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        records.append(json.loads(line))
            elif suffix == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                records = list(payload.get("likely_real", []))
            elif suffix == ".csv":
                with path.open(newline="", encoding="utf-8") as fh:
                    records = list(csv.DictReader(fh))
            else:
                raise ValueError(f"Unsupported confidence episodes file extension: {path.suffix}")
        else:
            records = list(source)

        faults: list[FaultEvidence] = []
        dq_items = _parse_dq_rows(data_quality)
        for rec in records:
            ev = rec.get("evidence") if isinstance(rec.get("evidence"), Mapping) else {}
            eq = str(rec.get("equipment_id", ""))
            rule_id = str(rec.get("rule_id", ""))
            is_dq = _opt_bool(rec.get("data_quality_rule") or ev.get("data_quality_rule"))
            faults.append(
                FaultEvidence(
                    equipment_id=eq,
                    rule_id=rule_id,
                    status="FAULT",
                    start=parse_utc(rec.get("start")),
                    end=parse_utc(rec.get("end")),
                    p_real=_opt_float(rec.get("p_real")),
                    p_false_positive=_opt_float(rec.get("p_false_positive")),
                    p_tuning=_opt_float(rec.get("p_tuning")),
                    confidence_label=rec.get("label") or None,
                    is_data_quality=is_dq,
                    site_id=str(rec.get("site_id") or ev.get("site_id") or ""),
                    reason=str(rec.get("reason") or ""),
                )
            )
            if _opt_bool(ev.get("poor_data_quality")) or (
                _opt_float(ev.get("stale_share")) is not None and float(ev["stale_share"]) > 0.25
            ):
                dq_items.append(
                    DataQualityEvidence(
                        equipment_id=eq,
                        flag="poor_data_quality",
                        detail=f"Confidence evidence flagged poor input data on {rule_id}",
                        site_id=str(rec.get("site_id") or ev.get("site_id") or ""),
                        start=parse_utc(rec.get("start")),
                        end=parse_utc(rec.get("end")),
                    )
                )

        return cls(
            faults=faults,
            data_quality_flags=dq_items,
            point_deviations=_parse_deviation_rows(deviations),
        )


def _episodes_from_sample_rows(
    rows: list[dict[str, Any]],
    want_status: set[str],
    gap: timedelta = timedelta(minutes=15),
) -> list[FaultEvidence]:
    """Group sample-level flag rows into fault episodes in Python (portable fallback)."""
    grouped: dict[tuple[str, str, str], list[tuple[datetime, bool]]] = {}
    for r in rows:
        ts = parse_utc(r.get("timestamp"))
        if ts is None:
            continue
        flag_val = str(r.get("flag", "")).strip().upper()
        is_fault = flag_val in want_status
        key = (str(r.get("site_id") or ""), str(r["equipment_id"]), str(r["rule_id"]))
        grouped.setdefault(key, []).append((ts, is_fault))

    episodes: list[FaultEvidence] = []

    def _flush(eq_id: str, rule_id: str, site_id: str, ep_start: datetime | None, ep_end: datetime | None) -> None:
        if ep_start is None or ep_end is None:
            return
        episodes.append(
            FaultEvidence(
                equipment_id=eq_id,
                rule_id=rule_id,
                status="FAULT",
                start=ep_start,
                end=ep_end,
                site_id=site_id,
            )
        )

    for (site_id, eq_id, rule_id), samples in sorted(grouped.items()):
        samples.sort(key=lambda item: item[0])
        ep_start: datetime | None = None
        ep_end: datetime | None = None
        last_fault: datetime | None = None
        for ts, is_fault in samples:
            if is_fault:
                if ep_start is None:
                    ep_start = ep_end = ts
                elif last_fault is not None and ts - last_fault <= gap:
                    ep_end = ts
                else:
                    _flush(eq_id, rule_id, site_id, ep_start, ep_end)
                    ep_start = ep_end = ts
                last_fault = ts
            elif ep_start is not None:
                _flush(eq_id, rule_id, site_id, ep_start, ep_end)
                ep_start = ep_end = last_fault = None
        _flush(eq_id, rule_id, site_id, ep_start, ep_end)
    return episodes


def _parse_dq_rows(data_quality: Any) -> list[DataQualityEvidence]:
    if data_quality is None:
        return []
    rows = data_quality.to_dict("records") if hasattr(data_quality, "to_dict") else list(data_quality)
    return [
        DataQualityEvidence(
            equipment_id=str(r["equipment_id"]),
            flag=str(r.get("flag", "untrusted")),
            point_id=str(r.get("point_id") or ""),
            detail=str(r.get("detail") or ""),
            site_id=str(r.get("site_id") or ""),
        )
        for r in rows
    ]


def _parse_deviation_rows(deviations: Any) -> list[PointDeviation]:
    if deviations is None:
        return []
    rows = deviations.to_dict("records") if hasattr(deviations, "to_dict") else list(deviations)
    out: list[PointDeviation] = []
    for r in rows:
        val = _opt_float(r.get("value_si"))
        if val is None:
            continue
        out.append(
            PointDeviation(
                equipment_id=str(r["equipment_id"]),
                role=str(r.get("role") or r.get("point_role") or ""),
                value_si=val,
                setpoint_si=_opt_float(r.get("setpoint_si")),
                deviation_si=_opt_float(r.get("deviation_si")),
                unit=str(r.get("unit") or ""),
                timestamp=parse_utc(r.get("timestamp")),
                site_id=str(r.get("site_id") or ""),
            )
        )
    return out

def confidence_sql_module():
    """Return ``open_fdd.ml.confidence_sql`` when the 5.0.22 confidence PR is present."""
    try:
        from open_fdd.ml import confidence_sql as mod
    except ImportError:
        return None
    return mod


class SqlEvidenceCollector:
    """Read-only SQL evidence loader for ``fdd.rule_result`` (SQLite / DuckDB / PostgreSQL).

    When ``open_fdd.ml.confidence_sql`` is installed (5.0.22 fault-confidence, PR #1786),
    episode building uses that module's portable ``episodes_sql`` (gaps-and-islands) and
    optional SI history uses ``history_sql`` against ``fdd.input_sample`` / ``fdd.point``.
    Until that module lands, ``load()`` falls back to a simple FAULT-row select so this
    package still runs on current master.
    """

    def __init__(
        self,
        conn: Any,
        *,
        table: str = "rule_result",
        layout: str = "results",
        columns: Mapping[str, str] | None = None,
        history_table: str | None = None,
        point_table: str | None = None,
        history_columns: Mapping[str, str] | None = None,
        sensitivity_frac: float = 0.10,
        source: Any = None,
        history: Any = None,
        fault_status: tuple[str, ...] = ("FAULT",),
        pass_status: tuple[str, ...] = ("PASS",),
    ) -> None:
        self.conn = conn
        self.table = table
        self.layout = layout
        self.columns = dict(columns or {})
        self.history_table = history_table
        self.point_table = point_table
        self.history_columns = dict(history_columns or {})
        self.sensitivity_frac = sensitivity_frac
        self.source = source
        self.history = history
        self.fault_status = tuple(fault_status)
        self.pass_status = tuple(pass_status)

    def _ident(self, name: str) -> str:
        if not isinstance(name, str) or not all(ch.isalnum() or ch in ("_", ".") for ch in name):
            raise ValueError(f"Invalid SQL identifier: {name!r}")
        return name

    def _present_columns(self) -> set[str]:
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM {self._ident(self.table)} WHERE 1=0")
        return {str(d[0]) for d in cur.description}

    def _site_select(self) -> tuple[str, str]:
        """Return (select expression, real column name or empty if site_id is absent)."""
        requested = self.columns.get("site_id", "site_id")
        present = {name.lower(): name for name in self._present_columns()}
        actual = present.get(requested.lower())
        if actual is None:
            return "''", ""
        return self._ident(actual), self._ident(actual)

    def _source(self, csql: Any, site_id: str | None) -> Any:
        if self.source is not None:
            src = self.source
            if site_id and getattr(src, "site_id", None) is None:
                from dataclasses import replace

                return replace(src, site_id=site_id)
            return src
        columns = dict(self.columns)
        present = {name.lower() for name in self._present_columns()}
        optional = ("site_id", "value", "threshold", "running") if self.layout == "flags" else (
            "site_id", "subject_key", "fault_hours", "covered_hours"
        )
        for key in optional:
            if key not in columns and key.lower() not in present:
                columns[key] = ""
        return csql.SourceMap(
            layout=self.layout,
            table=self.table,
            columns=columns,
            fault_status=self.fault_status,
            pass_status=self.pass_status,
            site_id=site_id,
        )

    def _history_map(self, csql: Any) -> Any | None:
        if self.history is not None:
            return self.history
        if not self.history_table:
            return None
        kw: dict[str, Any] = {"table": self.history_table, "columns": self.history_columns}
        if self.point_table is not None:
            kw["point_table"] = self.point_table
        return csql.HistoryMap(**kw)

    def load(self, *, site_id: str | None = None) -> DataFrameEvidenceCollector:
        csql = confidence_sql_module()
        if csql is None:
            return self._load_simple(site_id=site_id)
        src = self._source(csql, site_id)
        ph = csql.paramstyle(self.conn)
        sql, params = csql.episodes_sql(src, self.sensitivity_frac, ph)
        cols, rows = csql.fetch(self.conn, sql, params)
        records = [dict(zip(cols, row)) for row in rows]
        faults = [_fault_from_episode_row(r) for r in records]
        deviations: list[PointDeviation] = []
        hm = self._history_map(csql)
        if hm is not None and faults:
            deviations = self._load_history_deviations(csql, hm, faults, site_id=site_id)
        return DataFrameEvidenceCollector(faults=faults, point_deviations=deviations)

    def _load_simple(self, *, site_id: str | None) -> DataFrameEvidenceCollector:
        table = self._ident(self.table)
        if self.layout == "flags":
            ts = self._ident(self.columns.get("timestamp", "timestamp"))
            eq = self._ident(self.columns.get("equipment_id", "equipment_id"))
            rule = self._ident(self.columns.get("rule_id", "rule_id"))
            flag = self._ident(self.columns.get("flag", "flag"))
            site_expr, site_col = self._site_select()
            sql = (
                f"SELECT {ts} AS timestamp, {eq} AS equipment_id, {rule} AS rule_id, "
                f"{flag} AS flag, {site_expr} AS site_id FROM {table}"
            )
            params: list[Any] = []
            if site_id and site_col:
                sql += f" WHERE {site_col} = ?"
                params.append(site_id)
            cur = self.conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            return DataFrameEvidenceCollector.from_rule_results(rows, fault_statuses=self.fault_status)

        eq = self._ident(self.columns.get("equipment_id", "equipment_id"))
        rule = self._ident(self.columns.get("rule_id", "rule_id"))
        t0 = self._ident(self.columns.get("window_start", "window_start"))
        t1 = self._ident(self.columns.get("window_end", "window_end"))
        st = self._ident(self.columns.get("status", "status"))
        site_expr, site_col = self._site_select()
        sql = (
            f"SELECT {eq} AS equipment_id, {rule} AS rule_id, {t0} AS window_start, "
            f"{t1} AS window_end, {st} AS status, {site_expr} AS site_id FROM {table} "
            f"WHERE UPPER(CAST({st} AS VARCHAR)) = 'FAULT'"
        )
        params: list[Any] = []
        if site_id and site_col:
            sql += f" AND {site_col} = ?"
            params.append(site_id)
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return DataFrameEvidenceCollector.from_rule_results(rows, fault_statuses=self.fault_status)

    def _load_history_deviations(
        self,
        csql: Any,
        hm: Any,
        faults: list[FaultEvidence],
        *,
        site_id: str | None,
    ) -> list[PointDeviation]:
        """Last SI sample per (equipment, point) in each episode window, plus setpoint deviations when paired."""
        ph = csql.paramstyle(self.conn)
        by_site = bool(site_id and hm.col("site_id"))
        sql = csql.history_sql(hm, ph, by_site=by_site)
        samples: list[PointDeviation] = []
        seen: set[tuple[str, str]] = set()
        for fault in faults:
            if fault.equipment_id in seen and fault.start is None:
                continue
            key = (fault.site_id or site_id or "", fault.equipment_id)
            if key in seen:
                continue
            seen.add(key)
            if fault.start is None or fault.end is None:
                continue
            params: list[Any] = [fault.equipment_id, fault.start.strftime("%Y-%m-%dT%H:%M:%SZ"), fault.end.strftime("%Y-%m-%dT%H:%M:%SZ")]
            if by_site:
                params.append(site_id or fault.site_id)
            cols, rows = csql.fetch(self.conn, sql, params)
            by_point: dict[str, tuple[Any, float]] = {}
            for row in rows:
                rec = dict(zip(cols, row))
                val = _opt_float(rec.get("value"))
                ts = rec.get("ts")
                pid = str(rec.get("point_id") or "")
                if val is None or not pid:
                    continue
                prev = by_point.get(pid)
                if prev is None or (ts is not None and prev[0] is not None and ts >= prev[0]) or prev[0] is None:
                    by_point[pid] = (ts, val)
            role_of = {pid: pid for pid in by_point}
            # Optional role column is not in the portable history_sql projection; point_id is the role key.
            setpoints = {
                pid: val
                for pid, (_ts, val) in by_point.items()
                if pid.endswith(("-sp", "-setpoint", "Setpoint"))
            }
            for pid, (ts, val) in by_point.items():
                if pid in setpoints:
                    continue
                sp = setpoints.get(pid + "-sp") or setpoints.get(pid + "-setpoint") or setpoints.get(pid + "Setpoint")
                samples.append(
                    PointDeviation(
                        equipment_id=fault.equipment_id,
                        role=role_of[pid],
                        value_si=val,
                        setpoint_si=sp,
                        unit="",
                        timestamp=parse_utc(ts),
                        site_id=fault.site_id or (site_id or ""),
                    )
                )
        return samples


def _fault_from_episode_row(row: Mapping[str, Any]) -> FaultEvidence:
    start = parse_utc(row.get("start_ts") or row.get("start") or row.get("window_start"))
    end = parse_utc(row.get("end_ts") or row.get("end") or row.get("window_end"))
    return FaultEvidence(
        equipment_id=str(row["equipment_id"]),
        rule_id=str(row["rule_id"]),
        status="FAULT",
        start=start,
        end=end,
        p_real=_opt_float(row.get("p_real")),
        p_false_positive=_opt_float(row.get("p_false_positive")),
        p_tuning=_opt_float(row.get("p_tuning")),
        confidence_label=row.get("label") or row.get("confidence_label") or None,
        is_data_quality=_opt_bool(row.get("data_quality_rule") or row.get("is_data_quality")),
        site_id=str(row.get("site_id") or ""),
        reason=str(row.get("subject") or row.get("reason") or ""),
    )
