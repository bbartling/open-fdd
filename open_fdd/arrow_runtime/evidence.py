"""Structured FDD evidence payloads (Arrow-native, no pandas)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def missing_columns_evidence(
    *,
    fault_code: str,
    canonical_id: str,
    missing_roles: list[str],
    available_columns: list[str],
) -> dict[str, Any]:
    return {
        "ok": False,
        "fault_code": fault_code,
        "canonical_id": canonical_id,
        "reason": "DATA-MISSING",
        "missing_point_roles": list(missing_roles),
        "available_columns": list(available_columns),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def flag_evidence(
    *,
    fault_code: str,
    canonical_id: str,
    severity: str,
    confidence: float,
    measured: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    duration_minutes: float | None = None,
    percent_time_active: float | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "fault_code": fault_code,
        "canonical_id": canonical_id,
        "severity": severity,
        "confidence": round(float(confidence), 3),
        "measured": measured,
        "thresholds": thresholds or {},
        "duration_minutes": duration_minutes,
        "percent_time_active": percent_time_active,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_point_roles(
    table_columns: list[str],
    role_map: dict[str, str],
    required_roles: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Map Brick/logical roles to historian column names present on table."""
    cols = set(table_columns)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for role in required_roles:
        col = role_map.get(role) or role
        if col in cols:
            resolved[role] = col
        else:
            missing.append(role)
    return resolved, missing
