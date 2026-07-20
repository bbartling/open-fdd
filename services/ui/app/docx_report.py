"""Serve the single Generic RCx Word report from ``assets/reports`` (no python-docx).

Engineers replace the file in place; the UI only reads bytes from disk.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.rules import RULES
from app.rules.cookbook_catalog import CookbookRule
from app.rules.runner import infer_equipment_kind
from app.rcx_plots import RCX_FAMILY_ORDER

__all__ = [
    "REPORTS_DIR",
    "GENERIC_RCX_DOCX",
    "applicable_rules_for_equipment",
    "load_report_bytes",
    "load_generic_rcx_report",
    "report_path",
    "list_expected_report_files",
    "rcx_families",
]

REPORTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "reports"
GENERIC_RCX_DOCX = "Open-FDD_Generic_RCx_Report_v1.docx"


def report_path(filename: str) -> Path:
    return REPORTS_DIR / filename


def load_report_bytes(filename: str) -> bytes:
    """Read a committed report from ``assets/reports``."""
    path = report_path(filename)
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing prebuilt report `{filename}` under {REPORTS_DIR}. "
            "Paste your Word file there or restore from version control."
        )
    return path.read_bytes()


def load_generic_rcx_report() -> bytes:
    """Bytes for the single Overview Generic RCx Word template."""
    return load_report_bytes(GENERIC_RCX_DOCX)


def list_expected_report_files() -> list[str]:
    """Filenames the app expects under assets/reports."""
    return [GENERIC_RCX_DOCX]


def applicable_rules_for_equipment(
    equipment_id: str,
    *,
    equipment_type: str = "",
    mapped_df: pd.DataFrame | None = None,
    role_map: dict | None = None,
) -> list[CookbookRule]:
    """Canonical cookbook rules applicable to this device's equipment kind."""
    kind = infer_equipment_kind(
        equipment_id,
        equipment_type=equipment_type,
        df=mapped_df,
        role_map=role_map,
    )
    if kind == "unknown":
        return list(RULES)
    return [r for r in RULES if kind in r.equipment_kinds]


def rcx_families() -> tuple[str, ...]:
    """UI family order for RCx charts (report templates are no longer per-family)."""
    chart = list(RCX_FAMILY_ORDER)
    extras = [f for f in ("Heat pump", "Weather") if f not in chart]
    return tuple(chart + extras)
