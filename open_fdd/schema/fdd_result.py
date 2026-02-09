"""
Canonical real-time FDD result and event schema.

Foundation for writing to TimescaleDB and Grafana. Used by the continuous
diagnostic loop and analyst backfill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class FDDResult:
    """Single FDD result (one sample, one fault flag)."""

    ts: datetime
    site_id: str
    equipment_id: str
    fault_id: str
    flag_value: int  # 0 or 1
    evidence: Optional[dict[str, Any]] = None

    def to_row(self) -> tuple:
        """For INSERT into fault_results table."""
        return (
            self.ts,
            self.site_id,
            self.equipment_id,
            self.fault_id,
            self.flag_value,
            self.evidence,
        )


@dataclass
class FDDEvent:
    """Fault event (episode): contiguous run of fault=True."""

    site_id: str
    equipment_id: str
    fault_id: str
    start_ts: datetime
    end_ts: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    evidence: Optional[dict[str, Any]] = None

    def to_row(self) -> tuple:
        """For INSERT into fault_events table."""
        return (
            self.site_id,
            self.equipment_id,
            self.fault_id,
            self.start_ts,
            self.end_ts,
            self.duration_seconds,
            self.evidence,
        )


def fdd_result_to_row(r: FDDResult) -> tuple:
    """Alias for FDDResult.to_row()."""
    return r.to_row()


def fdd_event_to_row(e: FDDEvent) -> tuple:
    """Alias for FDDEvent.to_row()."""
    return e.to_row()


def results_from_runner_output(
    df, site_id: str, equipment_id: str, timestamp_col: str = "timestamp"
) -> list[FDDResult]:
    """
    Convert RuleRunner output DataFrame to list of FDDResult.
    One result per (ts, equipment, fault_id) where flag=1.
    """
    results = []
    flag_cols = [c for c in df.columns if c.endswith("_flag")]
    ts = df[timestamp_col]
    if hasattr(ts.iloc[0], "to_pydatetime"):
        ts = ts.dt.tz_localize(None) if ts.dt.tz else ts
    for i, row in df.iterrows():
        t = ts.iloc[i]
        if hasattr(t, "to_pydatetime"):
            t = t.to_pydatetime()
        for col in flag_cols:
            val = row.get(col, 0)
            flag_val = 1 if val else 0
            if flag_val:
                results.append(
                    FDDResult(
                        ts=t,
                        site_id=site_id,
                        equipment_id=equipment_id,
                        fault_id=col,
                        flag_value=flag_val,
                        evidence=None,
                    )
                )
    return results


def events_from_flag_series(
    df, flag_col: str, site_id: str, equipment_id: str, timestamp_col: str = "timestamp"
) -> list[FDDEvent]:
    """
    Extract fault events (contiguous True regions) from a flag column.
    """
    from open_fdd.reports import get_fault_events

    evs = get_fault_events(df, flag_col)
    out = []
    ts = df[timestamp_col]
    for start_iloc, end_iloc, _ in evs:
        start_ts = ts.iloc[start_iloc]
        end_ts = ts.iloc[end_iloc]
        if hasattr(start_ts, "to_pydatetime"):
            start_ts = start_ts.to_pydatetime()
        if hasattr(end_ts, "to_pydatetime"):
            end_ts = end_ts.to_pydatetime()
        dur = None
        if hasattr(start_ts, "timestamp") and hasattr(end_ts, "timestamp"):
            dur = int(end_ts.timestamp() - start_ts.timestamp())
        out.append(
            FDDEvent(
                site_id=site_id,
                equipment_id=equipment_id,
                fault_id=flag_col,
                start_ts=start_ts,
                end_ts=end_ts,
                duration_seconds=dur,
            )
        )
    return out
