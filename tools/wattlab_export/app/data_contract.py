"""Building / package data-contract audits — surface warnings, never invent data.

Produces a structured ``PackageHealthReport`` (Pydantic) so UI/agents can show a
short grade + counts instead of flooding the sidebar with per-row strings.
Full-resolution history and rule math are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.data_loader import _read_columns_map

Severity = Literal["info", "warn", "error"]
HealthGrade = Literal["ok", "degraded", "incomplete"]


class ContractIssue(BaseModel):
    """One normalized package-contract finding (aggregatable)."""

    code: str
    severity: Severity = "warn"
    message: str
    equipment_id: str | None = None
    count: int = 1
    samples: list[str] = Field(default_factory=list)


class TopologyHealth(BaseModel):
    vav_folder_count: int = 0
    mapped_count: int = 0
    missing_map_count: int = 0
    stale_map_id_count: int = 0
    coverage_pct: float = 100.0
    missing_samples: list[str] = Field(default_factory=list)
    stale_samples: list[str] = Field(default_factory=list)


class ColumnsHealth(BaseModel):
    equipment_with_extras: int = 0
    total_ignored_points: int = 0
    samples: list[str] = Field(default_factory=list)


class QualityHealth(BaseModel):
    equipment_flagged: int = 0
    samples: list[str] = Field(default_factory=list)


class PackageHealthReport(BaseModel):
    """Machine-readable package quality for UI summary + agent export."""

    grade: HealthGrade = "ok"
    issues: list[ContractIssue] = Field(default_factory=list)
    topology: TopologyHealth = Field(default_factory=TopologyHealth)
    columns: ColumnsHealth = Field(default_factory=ColumnsHealth)
    quality: QualityHealth = Field(default_factory=QualityHealth)
    summary_lines: list[str] = Field(default_factory=list)
    detail_lines: list[str] = Field(default_factory=list)

    def to_report_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _parse_utc(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.to_datetime(value, utc=True)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def load_quality_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def trusted_start_from_quality(quality: dict[str, Any] | None) -> pd.Timestamp | None:
    if not quality:
        return None
    for key in (
        "trusted_start_utc",
        "trusted_data_start_utc",
        "trusted_data_start",
        "trusted_start",
        "data_trusted_from",
    ):
        if key in quality:
            return _parse_utc(quality.get(key))
    nested = quality.get("quality") if isinstance(quality.get("quality"), dict) else None
    if nested:
        return trusted_start_from_quality(nested)
    return None


def _preview(ids: list[str], *, limit: int = 8) -> tuple[str, str]:
    preview = ", ".join(ids[:limit])
    extra = f" (+{len(ids) - limit} more)" if len(ids) > limit else ""
    return preview, extra


def audit_columns_vs_history(
    equipment_id: str,
    df: pd.DataFrame,
    columns_path: Path | None,
) -> tuple[list[str], dict[str, str], ContractIssue | None]:
    """Intersect columns.csv with history columns; warn on metadata-only points.

    Returns (legacy warning strings, col→role map for historized cols, optional issue).
    """
    warnings: list[str] = []
    if not columns_path or not Path(columns_path).is_file():
        return warnings, {}, None
    full_map = _read_columns_map(Path(columns_path))
    hist_cols = {str(c) for c in df.columns}
    present = {c: r for c, r in full_map.items() if c in hist_cols}
    missing = sorted(set(full_map) - hist_cols)
    issue: ContractIssue | None = None
    if missing:
        preview, extra = _preview(missing)
        msg = (
            f"{equipment_id}: columns.csv lists {len(missing)} point(s) absent from "
            f"history_wide.csv — ignored for mapping: {preview}{extra}"
        )
        warnings.append(msg)
        issue = ContractIssue(
            code="columns.metadata_only",
            severity="warn",
            message=msg,
            equipment_id=equipment_id,
            count=len(missing),
            samples=missing[:12],
        )
    return warnings, present, issue


def audit_quality_window(
    equipment_id: str,
    df: pd.DataFrame,
    quality: dict[str, Any] | None,
    *,
    parent_quality: dict[str, Any] | None = None,
    parent_id: str | None = None,
) -> tuple[list[str], list[ContractIssue]]:
    """Warn when quality trusted-start would zero out rows. Does not filter the frame."""
    warnings: list[str] = []
    issues: list[ContractIssue] = []
    q = quality
    source = "own quality.json"
    if q is None and parent_quality is not None:
        q = parent_quality
        source = f"parent AHU quality.json ({parent_id or 'parent'})"
    if q is None:
        return warnings, issues
    start = trusted_start_from_quality(q)
    if start is None:
        return warnings, issues
    if not isinstance(df.index, pd.DatetimeIndex) or df.empty:
        return warnings, issues
    data_end = df.index.max()
    data_start = df.index.min()
    trusted = df.index[df.index >= start]
    if len(trusted) == 0:
        msg = (
            f"{equipment_id}: {source} trusted_start={start} is after data end "
            f"{data_end} — would yield 0 trusted rows. Keeping full history "
            f"[{data_start} → {data_end}]; do not invent or backdate trusted data."
        )
        warnings.append(msg)
        issues.append(
            ContractIssue(
                code="quality.trusted_empty",
                severity="warn",
                message=msg,
                equipment_id=equipment_id,
                samples=[str(start)],
            )
        )
    elif start > data_start:
        dropped = int((df.index < start).sum())
        msg = (
            f"{equipment_id}: {source} trusted_start={start} drops "
            f"{dropped} early row(s) before trusted window "
            f"(data still loaded unfiltered; filter only if caller opts in)."
        )
        warnings.append(msg)
        issues.append(
            ContractIssue(
                code="quality.trusted_trims",
                severity="info",
                message=msg,
                equipment_id=equipment_id,
                count=dropped,
                samples=[str(start)],
            )
        )
    return warnings, issues


def load_vav_to_ahu_map(building_root: Path) -> dict[str, str]:
    """Return VAV id → AHU id from optional ``vav_to_ahu_simple.csv``."""
    path = Path(building_root) / "vav_to_ahu_simple.csv"
    if not path.is_file():
        return {}
    try:
        topo = pd.read_csv(path)
    except Exception:
        return {}
    cols = {c.lower(): c for c in topo.columns}
    vav_col = cols.get("vav") or cols.get("vav_id") or cols.get("terminal") or cols.get("equipment_id")
    ahu_col = cols.get("ahu") or cols.get("ahu_id") or cols.get("parent") or cols.get("serves")
    if not vav_col or not ahu_col:
        if topo.shape[1] >= 2:
            vav_col, ahu_col = topo.columns[0], topo.columns[1]
        else:
            return {}
    out: dict[str, str] = {}
    for _, row in topo.iterrows():
        v = str(row[vav_col]).strip()
        a = str(row[ahu_col]).strip()
        if v and a and v.lower() not in {"vav", "vav_id", "nan"}:
            out[v] = a
    return out


def infer_parent_ahu_from_path(eq_folder: Path, building_root: Path) -> str | None:
    """Best-effort parent AHU from folder layout (e.g. VAV under an AHU tree)."""
    try:
        rel = eq_folder.resolve().relative_to(Path(building_root).resolve())
    except Exception:
        return None
    parts = list(rel.parts)
    for part in parts:
        up = part.upper()
        if up.startswith("AHU") and up != eq_folder.name.upper():
            return part
    return None


def _is_vav_equipment(eq: dict[str, Any]) -> bool:
    eid = str(eq.get("equipment_id") or "")
    folder = Path(eq.get("folder") or ".")
    parts = [p.upper() for p in folder.parts]
    return "VAV" in parts or eid.upper().startswith("VAV")


def audit_building_topology(
    building_root: Path,
    equipment: list[dict[str, Any]],
) -> tuple[list[str], dict[str, str], TopologyHealth, list[ContractIssue]]:
    """Warn on VAV↔topology mismatches. Returns warnings, map, health, issues."""
    warnings: list[str] = []
    issues: list[ContractIssue] = []
    topo = load_vav_to_ahu_map(building_root)
    vav_ids = [str(eq.get("equipment_id") or "") for eq in equipment if _is_vav_equipment(eq)]
    vav_set = set(vav_ids)

    missing_topo = sorted(v for v in vav_ids if v not in topo)
    orphan_topo = sorted(v for v in topo if v not in vav_set)
    mapped = len(vav_ids) - len(missing_topo)
    coverage = (100.0 * mapped / len(vav_ids)) if vav_ids else 100.0

    health = TopologyHealth(
        vav_folder_count=len(vav_ids),
        mapped_count=mapped,
        missing_map_count=len(missing_topo),
        stale_map_id_count=len(orphan_topo),
        coverage_pct=round(coverage, 1),
        missing_samples=missing_topo[:12],
        stale_samples=orphan_topo[:12],
    )

    if missing_topo:
        preview, extra = _preview(missing_topo)
        msg = (
            f"Topology: {len(missing_topo)} VAV folder(s) not in vav_to_ahu_simple.csv "
            f"— parent-AHU fallback via path/quality only: {preview}{extra}"
        )
        warnings.append(msg)
        issues.append(
            ContractIssue(
                code="topology.missing_vav_map",
                severity="warn",
                message=msg,
                count=len(missing_topo),
                samples=missing_topo[:12],
            )
        )

    if orphan_topo:
        preview, extra = _preview(orphan_topo)
        msg = (
            f"Topology: {len(orphan_topo)} vav_to_ahu_simple.csv id(s) have no VAV folder: "
            f"{preview}{extra}"
        )
        warnings.append(msg)
        # Non-VAV ids in the VAV column are a stronger signal of a bad export
        severity: Severity = (
            "error"
            if any(not s.upper().startswith("VAV") for s in orphan_topo)
            else "warn"
        )
        issues.append(
            ContractIssue(
                code="topology.stale_map_ids",
                severity=severity,
                message=msg,
                count=len(orphan_topo),
                samples=orphan_topo[:12],
            )
        )
    return warnings, topo, health, issues


def audit_equipment_package(
    equipment_id: str,
    df: pd.DataFrame,
    eq_folder: Path,
    building_root: Path,
    topo: dict[str, str],
) -> tuple[list[str], list[ContractIssue]]:
    """Full per-equipment contract warnings (columns + quality)."""
    warnings: list[str] = []
    issues: list[ContractIssue] = []
    cols_path = eq_folder / "columns.csv"
    col_warn, present_map, col_issue = audit_columns_vs_history(
        equipment_id, df, cols_path if cols_path.is_file() else None
    )
    warnings.extend(col_warn)
    if col_issue:
        issues.append(col_issue)
    if present_map:
        df.attrs["columns_roles_present"] = present_map
        df.attrs["columns_roles_ignored"] = (
            sorted(set(_read_columns_map(cols_path)) - set(present_map))
            if cols_path.is_file()
            else []
        )

    own_q = load_quality_json(eq_folder / "quality.json")
    parent_id = topo.get(equipment_id) or infer_parent_ahu_from_path(eq_folder, building_root)
    parent_q = None
    if parent_id:
        candidate = Path(building_root) / parent_id / "quality.json"
        if not candidate.is_file():
            for p in Path(building_root).rglob("quality.json"):
                if p.parent.name == parent_id:
                    candidate = p
                    break
        parent_q = load_quality_json(candidate)
    q_warn, q_issues = audit_quality_window(
        equipment_id,
        df,
        own_q,
        parent_quality=parent_q if own_q is None else None,
        parent_id=parent_id,
    )
    warnings.extend(q_warn)
    issues.extend(q_issues)
    if own_q is None and parent_q is not None:
        msg = (
            f"{equipment_id}: no quality.json — using parent AHU '{parent_id}' "
            "quality for trust checks only"
        )
        warnings.append(msg)
        issues.append(
            ContractIssue(
                code="quality.parent_fallback",
                severity="info",
                message=msg,
                equipment_id=equipment_id,
                samples=[str(parent_id)],
            )
        )
    return warnings, issues


def _grade_health(
    topology: TopologyHealth,
    issues: list[ContractIssue],
) -> HealthGrade:
    if any(i.severity == "error" for i in issues):
        return "incomplete"
    if topology.vav_folder_count and topology.coverage_pct < 50.0:
        return "incomplete"
    if any(i.severity == "warn" for i in issues):
        return "degraded"
    if topology.missing_map_count or topology.stale_map_id_count:
        return "degraded"
    return "ok"


def _build_summary(
    grade: HealthGrade,
    topology: TopologyHealth,
    columns: ColumnsHealth,
    quality: QualityHealth,
    issues: list[ContractIssue],
) -> list[str]:
    lines: list[str] = [
        f"Dataset health: {grade.upper()} "
        f"(non-fatal — load succeeded; topology/metadata may be incomplete)."
    ]
    if topology.vav_folder_count:
        lines.append(
            f"Topology: {topology.mapped_count}/{topology.vav_folder_count} VAVs in "
            f"vav_to_ahu_simple.csv ({topology.coverage_pct:.0f}% coverage)"
            + (
                f"; {topology.stale_map_id_count} stale map id(s)"
                if topology.stale_map_id_count
                else ""
            )
        )
    if columns.total_ignored_points:
        lines.append(
            f"columns.csv: {columns.total_ignored_points} metadata-only point(s) across "
            f"{columns.equipment_with_extras} equipment (ignored for mapping; history is truth)"
        )
    if quality.equipment_flagged:
        lines.append(
            f"Quality windows: {quality.equipment_flagged} equipment flagged "
            "(history kept unfiltered)"
        )
    # Surface non-topology/columns errors briefly (already counted above when possible)
    for issue in issues:
        if issue.code.startswith(("topology.", "columns.", "quality.")):
            continue
        if issue.severity in {"warn", "error"} and len(lines) < 5:
            lines.append(issue.message.split(" — ")[0][:160])
    return lines[:5]


def build_package_health(
    detail_lines: list[str],
    issues: list[ContractIssue],
    topology: TopologyHealth,
    columns: ColumnsHealth,
    quality: QualityHealth,
) -> PackageHealthReport:
    grade = _grade_health(topology, issues)
    return PackageHealthReport(
        grade=grade,
        issues=issues,
        topology=topology,
        columns=columns,
        quality=quality,
        summary_lines=_build_summary(grade, topology, columns, quality, issues),
        detail_lines=list(detail_lines),
    )


def audit_package_dir(
    building_root: Path,
    frames: dict[str, pd.DataFrame],
    equipment: list[dict[str, Any]],
) -> tuple[list[str], PackageHealthReport]:
    """Run building-level + per-equip audits; mutate frame attrs for present roles.

    Returns ``(detail_warning_strings, PackageHealthReport)``.
    """
    detail, topo, topology_health, issues = audit_building_topology(building_root, equipment)
    by_id = {str(e["equipment_id"]): e for e in equipment}
    col_equip = 0
    col_ignored = 0
    col_samples: list[str] = []
    quality_equip: set[str] = set()
    quality_samples: list[str] = []

    for eid, df in frames.items():
        eq = by_id.get(eid)
        if not eq:
            continue
        folder = Path(eq["folder"])
        eq_warn, eq_issues = audit_equipment_package(
            equipment_id=eid,
            df=df,
            eq_folder=folder,
            building_root=building_root,
            topo=topo,
        )
        detail.extend(eq_warn)
        issues.extend(eq_issues)
        for iss in eq_issues:
            if iss.code == "columns.metadata_only":
                col_equip += 1
                col_ignored += int(iss.count)
                if len(col_samples) < 8:
                    col_samples.append(f"{eid}: {iss.count} ignored")
            if iss.code.startswith("quality."):
                quality_equip.add(eid)
                if len(quality_samples) < 8:
                    quality_samples.append(eid)

    columns_health = ColumnsHealth(
        equipment_with_extras=col_equip,
        total_ignored_points=col_ignored,
        samples=col_samples,
    )
    quality_health = QualityHealth(
        equipment_flagged=len(quality_equip),
        samples=quality_samples,
    )
    health = build_package_health(detail, issues, topology_health, columns_health, quality_health)
    return detail, health
