"""Poll registered edge sites and append central portfolio CSV history."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from portfolio.collector.edge_client import api_post, fetch_portfolio_rollup, login
from portfolio.store.csv_store import append_rollup, save_rollup_json


@dataclass
class SiteConfig:
    site_id: str
    name: str
    base_url: str
    username: str
    password: str
    run_checkin: bool = False
    checkin_run_batch: bool = False


def _portfolio_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_sites_config(path: Path | None = None) -> list[SiteConfig]:
    if path is None:
        try:
            from portfolio.central.paths import sites_path as _sites_path

            cfg_path = _sites_path()
        except ImportError:
            cfg_path = _portfolio_root() / "sites.json"
    else:
        cfg_path = path
    if not cfg_path.is_file():
        example = _portfolio_root() / "sites.json.example"
        raise FileNotFoundError(
            f"missing {cfg_path} — copy {example} to sites.json and add your buildings"
        )
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    sites = raw.get("sites") if isinstance(raw, dict) else raw
    if not isinstance(sites, list):
        raise ValueError("sites.json must contain a 'sites' array")
    out: list[SiteConfig] = []
    for item in sites:
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        if not site_id or not base_url:
            continue
        user = str(item.get("username") or os.environ.get("OFDD_AGENT_USER") or "agent")
        password = str(item.get("password") or "")
        if not password:
            acme_user = os.environ.get("ACME_INTEGRATOR_USER", "integrator")
            if user == acme_user:
                password = str(os.environ.get("ACME_INTEGRATOR_PASSWORD") or "")
            elif user == os.environ.get("OFDD_AGENT_USER", "agent"):
                password = str(os.environ.get("OFDD_AGENT_PASSWORD") or "")
            else:
                password = str(os.environ.get("OFDD_INTEGRATOR_PASSWORD") or "")
        out.append(
            SiteConfig(
                site_id=site_id,
                name=str(item.get("name") or site_id),
                base_url=base_url,
                username=user,
                password=password,
                run_checkin=bool(item.get("run_checkin")),
                checkin_run_batch=bool(item.get("checkin_run_batch")),
            )
        )
    return out


def collect_site(site: SiteConfig, *, data_dir: Path | None = None) -> dict[str, Any]:
    if not site.password:
        raise RuntimeError(f"{site.site_id}: missing password (sites.json or OFDD_AGENT_PASSWORD)")
    token = login(site.base_url, username=site.username, password=site.password)
    if site.run_checkin:
        api_post(
            site.base_url,
            token,
            "/api/building-agent/checkin",
            {
                "site_id": site.site_id,
                "run_fdd_batch": site.checkin_run_batch,
                "write_memory": True,
                "window_minutes": 60,
            },
        )
    rollup = fetch_portfolio_rollup(site.base_url, token, site_id=site.site_id)
    save_rollup_json(rollup, site_id=site.site_id, data_dir=data_dir)
    counts = append_rollup(
        rollup,
        site_name=site.name,
        base_url=site.base_url,
        data_dir=data_dir,
        agent_checkin=site.run_checkin,
    )
    return {"ok": True, "site_id": site.site_id, "rollup": rollup, "csv_rows": counts}


def collect_all(
    *,
    sites_path: Path | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    for site in load_sites_config(sites_path):
        try:
            results.append(collect_site(site, data_dir=data_dir))
        except Exception as exc:
            err = str(exc)
            stub = {
                "ok": False,
                "site_id": site.site_id,
                "generated_at": started,
                "building": {"traffic": "unknown", "status": "error"},
                "faults": {"active_count": 0, "active_by_code": {}},
                "overrides": {"operator_override_points": 0, "points": []},
                "runtime_metrics": {},
            }
            append_rollup(
                stub,
                site_name=site.name,
                base_url=site.base_url,
                data_dir=data_dir,
                error=err,
            )
            results.append({"ok": False, "site_id": site.site_id, "error": err})
    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_count == len(results),
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "sites_polled": len(results),
        "sites_ok": ok_count,
        "results": results,
    }
