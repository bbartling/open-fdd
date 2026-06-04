"""Resolve edge site pack paths from site_id + building_id (no hardcoded customer names)."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def pack_dir(site_id: str, building_id: str, *, source: str = "backup") -> Path:
    """``source``: ``backup`` → edge_backup/local; ``config`` → edge_config."""
    if source not in {"backup", "config"}:
        raise ValueError(f"pack_dir source must be 'backup' or 'config', got {source!r}")
    base = "edge_backup/local" if source == "backup" else "edge_config"
    return repo_root() / base / site_id.strip() / building_id.strip()


def points_csv(
    site_id: str,
    building_id: str,
    *,
    prefer_gl36_poll: bool = True,
    source: str = "backup",
) -> Path:
    """Best-effort points CSV for a site pack (poll export preferred when present)."""
    root = pack_dir(site_id, building_id, source=source)
    candidates = (
        (root / "points.gl36_poll.csv", root / "points.csv")
        if prefer_gl36_poll
        else (root / "points.csv", root / "points.gl36_poll.csv")
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def model_json_path(site_id: str, building_id: str | None = None) -> Path:
    sid = site_id.strip()
    if building_id and building_id.strip():
        name = f"{sid}_{building_id.strip()}_gl36_model.json"
    else:
        name = f"{sid}_gl36_model.json"
    return repo_root() / "workspace" / "data" / name


def equipment_id(site_id: str, building_id: str, system_id: str) -> str:
    """BRICK equipment id: ``{site}-{building}-{system}`` (slugged)."""
    sid = site_id.strip().lower().replace("_", "-")
    bid = building_id.strip().lower().replace("_", "-")
    sys_slug = (system_id or "equipment").strip().lower().replace("_", "-")
    return f"{sid}-{bid}-{sys_slug}"


def rule_id_prefix(site_id: str) -> str:
    return site_id.strip().lower().replace("_", "-")
