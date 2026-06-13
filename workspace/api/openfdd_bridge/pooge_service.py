"""Guarded factory reset / edge wipe — allowlisted path cleanup for job-site redeploys."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import data_dir, workspace_dir

POOGE_CONFIRMATION = "RESET THIS EDGE"


@dataclass
class PoogeRequest:
    dry_run: bool = True
    confirmation: str = ""
    clear_historian: bool = True
    clear_bacnet: bool = True
    clear_model: bool = False
    clear_rules: bool = False
    clear_exports: bool = True
    preserve_auth: bool = True
    preserve_network: bool = True
    preserve_site_identity: bool = True
    linux_update: bool = False
    docker_update: bool = False


def _repo_root() -> Path:
    from .paths import repo_root

    return repo_root()


def _resolve_allowed(path: Path) -> Path | None:
    """Return path only if it stays under workspace or data dir."""
    try:
        resolved = path.resolve()
        for root in (workspace_dir().resolve(), data_dir().resolve()):
            if resolved == root or root in resolved.parents:
                return resolved
    except OSError:
        return None
    return None


def _targets(req: PoogeRequest) -> list[dict[str, Any]]:
    ws = workspace_dir()
    data = data_dir()
    items: list[dict[str, Any]] = []

    if req.clear_historian:
        root = _resolve_allowed(data / "feather_store")
        if root and root.is_dir():
            items.append({"action": "remove_tree", "path": str(root), "label": "historian feather_store"})

    if req.clear_bacnet:
        polls = _resolve_allowed(ws / "bacnet" / "polls")
        if polls and polls.is_dir():
            items.append({"action": "clear_dir", "path": str(polls), "label": "BACnet poll scratch"})
        for name in ("points_discovered.csv",):
            p = _resolve_allowed(ws / "bacnet" / "commissioning" / name)
            if p and p.is_file():
                items.append({"action": "truncate_file", "path": str(p), "label": f"BACnet {name}"})

    if req.clear_model:
        for rel in ("model.json", "data_model.ttl"):
            p = _resolve_allowed(data / rel)
            if p and p.is_file():
                items.append({"action": "remove_file", "path": str(p), "label": rel})
        ttl_ws = _resolve_allowed(ws / "data" / "data_model.ttl")
        if ttl_ws and ttl_ws.is_file():
            items.append({"action": "remove_file", "path": str(ttl_ws), "label": "workspace data_model.ttl"})

    if req.clear_rules:
        rs = _resolve_allowed(data / "rules_store.json")
        if rs and rs.is_file():
            items.append({"action": "remove_file", "path": str(rs), "label": "rules_store.json"})
        rules_py = _resolve_allowed(data / "rules_py")
        if rules_py and rules_py.is_dir():
            items.append({"action": "clear_dir", "path": str(rules_py), "label": "rules_py sources"})

    if req.clear_exports:
        for rel in (
            "exports",
            "reports",
            "tmp",
            "playground_exports",
        ):
            p = _resolve_allowed(data / rel)
            if p and p.exists():
                items.append({"action": "remove_tree", "path": str(p), "label": f"exports {rel}"})
        ws_exports = _resolve_allowed(ws / "exports")
        if ws_exports and ws_exports.exists():
            items.append({"action": "remove_tree", "path": str(ws_exports), "label": "workspace exports"})

    if req.linux_update:
        items.append({"action": "linux_update", "path": "", "label": "apt upgrade (host)"})
    if req.docker_update:
        items.append({"action": "docker_update", "path": "", "label": "pull GHCR images + recreate containers"})

    preserved: list[str] = []
    if req.preserve_auth:
        preserved.extend(["auth.env.local", "workspace/auth env files"])
    if req.preserve_network:
        preserved.append("commission.env BACNET_BIND / network settings")
    if req.preserve_site_identity:
        preserved.append("site_id / building_id in commission.env and model")

    return items


def _clear_directory(path: Path, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    if not path.is_dir():
        return actions
    for child in path.iterdir():
        actions.append(f"delete {child}")
        if not dry_run:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    return actions


def preview_pooge(req: PoogeRequest) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": req.dry_run,
        "targets": _targets(req),
        "preserve_auth": req.preserve_auth,
        "preserve_network": req.preserve_network,
        "preserve_site_identity": req.preserve_site_identity,
    }


def run_pooge(req: PoogeRequest, *, user: dict[str, Any] | None = None) -> dict[str, Any]:
    if req.confirmation != POOGE_CONFIRMATION:
        return {"ok": False, "error": f"confirmation must be exactly: {POOGE_CONFIRMATION}"}

    audit: list[str] = []
    errors: list[str] = []
    targets = _targets(req)

    for item in targets:
        action = item.get("action")
        label = str(item.get("label") or action)
        path_raw = str(item.get("path") or "")

        if action == "linux_update":
            audit.append(f"linux_update: {'skipped (dry-run)' if req.dry_run else 'requested'}")
            if not req.dry_run:
                try:
                    proc = subprocess.run(
                        ["apt-get", "update"],
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False,
                    )
                    audit.append(f"apt-get update exit={proc.returncode}")
                    proc2 = subprocess.run(
                        ["apt-get", "upgrade", "-y"],
                        capture_output=True,
                        text=True,
                        timeout=1800,
                        check=False,
                    )
                    audit.append(f"apt-get upgrade exit={proc2.returncode}")
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(f"linux_update failed: {exc}")
            continue

        if action == "docker_update":
            audit.append(f"docker_update: {'skipped (dry-run)' if req.dry_run else 'requested'}")
            if not req.dry_run:
                script = _repo_root() / "scripts" / "upgrade_edge_ghcr.sh"
                if script.is_file():
                    try:
                        proc = subprocess.run(
                            [str(script)],
                            capture_output=True,
                            text=True,
                            timeout=1800,
                            check=False,
                            cwd=str(_repo_root()),
                        )
                        audit.append(f"upgrade_edge_ghcr.sh exit={proc.returncode}")
                        if proc.returncode != 0:
                            errors.append((proc.stderr or proc.stdout or "upgrade failed")[-500:])
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        errors.append(f"docker_update failed: {exc}")
                else:
                    errors.append("upgrade_edge_ghcr.sh not found")
            continue

        if not path_raw:
            continue
        path = Path(path_raw)
        allowed = _resolve_allowed(path)
        if allowed is None:
            errors.append(f"blocked path traversal: {path_raw}")
            continue

        audit.append(f"{action} {label}: {allowed}")
        if req.dry_run:
            continue

        try:
            if action == "remove_tree" and allowed.is_dir():
                shutil.rmtree(allowed)
                allowed.mkdir(parents=True, exist_ok=True)
            elif action == "remove_file" and allowed.is_file():
                allowed.unlink(missing_ok=True)
            elif action == "truncate_file" and allowed.is_file():
                allowed.write_text("", encoding="utf-8")
            elif action == "clear_dir" and allowed.is_dir():
                audit.extend(_clear_directory(allowed, dry_run=False))
        except OSError as exc:
            errors.append(f"{label}: {exc}")

    from .audit import write_audit

    write_audit(
        event_type="host.maintenance",
        action="pooge_reset",
        outcome="success" if not errors else "partial",
        user=user or {},
        resource_type="host",
        detail={"dry_run": req.dry_run, "audit": audit[-20:], "errors": errors},
    )

    return {
        "ok": not errors,
        "dry_run": req.dry_run,
        "audit": audit,
        "errors": errors,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "user": (user or {}).get("sub") or (user or {}).get("username"),
    }
