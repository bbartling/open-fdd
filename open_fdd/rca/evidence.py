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
        """True when this fault overlaps ``[window_start - tolerance, window_end + tolerance]``."""
        if window_start is None or window_end is None or self.start is None:
            return True
        s_end = self.end if self.end is not None else self.start
        return s_end >= (window_start - tolerance) and self.start <= (window_end + tolerance)


@dataclass(frozen=True)
class DataQualityEvidence:
    """Data-quality or trust warning on a node or its sensor inputs."""

    equipment_id: str
    flag: str
    point_id: str = ""
    detail: str = ""
    site_id: str = ""


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
        dq = [d for d in self._dq if d.equipment_id.lower() == eq_low and match_site(d.site_id)]
        devs = [
            p
            for p in self._devs
            if p.equipment_id.lower() == eq_low
            and match_site(p.site_id)
            and (
                window_start is None
                or window_end is None
                or p.timestamp is None
                or (window_start - tolerance) <= p.timestamp <= (window_end + tolerance)
            )
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
    grouped: dict[tuple[str, str, str], list[datetime]] = {}
    for r in rows:
        flag_val = str(r.get("flag", "")).strip().upper()
        if flag_val not in want_status and flag_val != "1":
            continue
        ts = parse_utc(r.get("timestamp"))
        if ts is None:
            continue
        key = (str(r.get("site_id") or ""), str(r["equipment_id"]), str(r["rule_id"]))
        grouped.setdefault(key, []).append(ts)

    episodes: list[FaultEvidence] = []
    for (site_id, eq_id, rule_id), stamps in sorted(grouped.items()):
        stamps.sort()
        ep_start = stamps[0]
        ep_end = stamps[0]
        for ts in stamps[1:]:
            if ts - ep_end <= gap:
                ep_end = ts
            else:
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
                ep_start = ep_end = ts
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


class SqlEvidenceCollector:
    """Read-only SQL evidence loader for ``fdd.rule_result`` (SQLite / DuckDB / DBAPI).

    TODO(5.0.22): Share episode SQL directly with ``open_fdd.ml.confidence_sql`` and add
    SI point-deviation queries against ``fdd.input_sample`` + ``fdd.point``.
    """

    def __init__(self, conn: Any, *, table: str = "rule_result") -> None:
        self.conn = conn
        self.table = table

    def load(self, *, site_id: str | None = None) -> DataFrameEvidenceCollector:
        if not all(ch.isalnum() or ch in ("_", ".") for ch in self.table):
            raise ValueError(f"Invalid SQL table identifier: {self.table!r}")
        sql = (
            f"SELECT equipment_id, rule_id, window_start, window_end, status "
            f"FROM {self.table} WHERE UPPER(status) = 'FAULT'"
        )
        params: tuple[Any, ...] = ()
        if site_id:
            sql += " AND site_id = ?"
            params = (site_id,)
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return DataFrameEvidenceCollector.from_rule_results(rows)