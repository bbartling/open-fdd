"""Config for analyst pipeline (ingest, brick, run_fdd, sparql)."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class AnalystConfig:
    """Configurable paths and params for analyst pipeline."""

    data_root: Path = field(default_factory=lambda: Path("data"))
    reports_root: Path = field(default_factory=lambda: Path("reports"))
    rules_root: Path = field(default_factory=lambda: Path("rules"))
    sparql_dir: Path = field(default_factory=lambda: Path("sparql"))

    sp_data_zip: Path | None = None
    sp_extract_dir: Path | None = None

    equipment_catalog: Path | None = None
    heat_pumps_csv: Path | None = None
    brick_ttl: Path | None = None
    report_docx: Path | None = None

    resample_freq: str = "5min"
    rolling_window: int = 6
    site_name: str = "Creekside Elementary"
    building: str = "Sun Prairie School District"

    def __post_init__(self) -> None:
        base = self.data_root
        self.equipment_catalog = self.equipment_catalog or base / "equipment.csv"
        self.heat_pumps_csv = self.heat_pumps_csv or base / "heat_pumps.csv"
        self.brick_ttl = self.brick_ttl or base / "data_model.ttl"
        self.report_docx = (
            self.report_docx or self.reports_root / "heat_pump_report.docx"
        )
        if self.sp_data_zip is None:
            self.sp_data_zip = Path(
                os.getenv("SP_DATA_ZIP", str(base.parent / "SP_Data.zip"))
            )
        if self.sp_extract_dir is None:
            self.sp_extract_dir = base.parent / "sp_extract"


def default_analyst_config(project_root: Path | None = None) -> AnalystConfig:
    """Build config from project root (e.g. analyst/ or open-fdd-datalake/)."""
    root = project_root or Path.cwd()
    return AnalystConfig(
        data_root=root / "data",
        reports_root=root / "reports",
        rules_root=root / "rules",
        sparql_dir=root / "sparql",
    )
