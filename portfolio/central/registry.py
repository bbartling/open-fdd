"""Edge site registry with last check-in metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from portfolio.collector.collector import SiteConfig, load_sites_config


def _portfolio_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _state_path(data_dir: Path | None = None) -> Path:
    root = data_dir or (_portfolio_root() / "data")
    root.mkdir(parents=True, exist_ok=True)
    return root / "registry_state.json"


@dataclass
class EdgeSiteRecord:
    site_id: str
    name: str
    base_url: str
    enabled: bool = True
    last_checkin_at: str = ""
    last_validation_at: str = ""
    last_traffic: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_registry_state(*, data_dir: Path | None = None) -> dict[str, Any]:
    path = _state_path(data_dir)
    if not path.is_file():
        return {"sites": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {"sites": {}}


def save_registry_state(state: dict[str, Any], *, data_dir: Path | None = None) -> None:
    path = _state_path(data_dir)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def list_edge_sites(
    *,
    sites_path: Path | None = None,
    data_dir: Path | None = None,
) -> list[EdgeSiteRecord]:
    configs = load_sites_config(sites_path)
    state = load_registry_state(data_dir=data_dir)
    by_id = state.get("sites") if isinstance(state.get("sites"), dict) else {}
    out: list[EdgeSiteRecord] = []
    for cfg in configs:
        meta = by_id.get(cfg.site_id) if isinstance(by_id.get(cfg.site_id), dict) else {}
        out.append(
            EdgeSiteRecord(
                site_id=cfg.site_id,
                name=cfg.name,
                base_url=cfg.base_url,
                enabled=bool(meta.get("enabled", True)),
                last_checkin_at=str(meta.get("last_checkin_at") or ""),
                last_validation_at=str(meta.get("last_validation_at") or ""),
                last_traffic=str(meta.get("last_traffic") or ""),
                last_error=str(meta.get("last_error") or ""),
            )
        )
    return out


def touch_site(
    site_id: str,
    *,
    checkin: bool = False,
    validation: bool = False,
    traffic: str = "",
    error: str = "",
    data_dir: Path | None = None,
) -> None:
    state = load_registry_state(data_dir=data_dir)
    sites = state.setdefault("sites", {})
    if not isinstance(sites, dict):
        sites = {}
        state["sites"] = sites
    row = sites.setdefault(site_id, {})
    if not isinstance(row, dict):
        row = {}
        sites[site_id] = row
    now = datetime.now(timezone.utc).isoformat()
    if checkin:
        row["last_checkin_at"] = now
    if validation:
        row["last_validation_at"] = now
    if traffic:
        row["last_traffic"] = traffic
    if error:
        row["last_error"] = error
    elif error == "" and "last_error" in row and validation:
        row["last_error"] = ""
    save_registry_state(state, data_dir=data_dir)


def site_config_for(site_id: str, *, sites_path: Path | None = None) -> SiteConfig:
    for cfg in load_sites_config(sites_path):
        if cfg.site_id == site_id:
            return cfg
    raise KeyError(f"unknown site_id {site_id!r}")
