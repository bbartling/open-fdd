"""Mirror Edge BRICK TTL to RCx Central data volume for local SPARQL."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.central.paths import site_ttl_manifest_path, site_ttl_path
from portfolio.central.ttl_from_export import build_ttl_from_model
from portfolio.collector.edge_client import EdgeClient, api_get_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_ttl(site_id: str, text: str, *, manifest_extra: dict[str, Any]) -> dict[str, Any]:
    dest = site_ttl_path(site_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
        os.replace(tmp_name, dest)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {
        "site_id": site_id,
        "synced_at": _utc_now(),
        "bytes": len(text.encode("utf-8")),
        "sha256": digest,
        "ttl_path": str(dest),
        **manifest_extra,
    }
    site_ttl_manifest_path(site_id).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def mirror_site_ttl(site_id: str, *, sync_edge: bool = True) -> dict[str, Any]:
    """Build TTL from Edge model export and persist under Central ``data/sites/{site_id}/model/``.

    Optionally triggers ``POST /api/model/sync-ttl`` on Edge first so on-site TTL stays aligned
    when the Edge image includes current ``ttl_service`` mapping (``brick_type`` → Brick class).
    """
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    client = EdgeClient(site.base_url)

    edge_ttl_synced = False
    edge_ttl_error: str | None = None
    if sync_edge:
        try:
            client.api_post("/api/model/sync-ttl", {}, token=token)
            edge_ttl_synced = True
        except RuntimeError as exc:
            edge_ttl_error = str(exc)[:300]

    model = client.api_get("/api/model/export", token=token)
    text = build_ttl_from_model(model)
    if not text.strip():
        raise RuntimeError("TTL build from model export returned empty text")

    manifest = _write_ttl(
        site_id,
        text,
        manifest_extra={
            "source": "model_export",
            "edge_ttl_synced": edge_ttl_synced,
            "edge_ttl_error": edge_ttl_error,
            "equipment_count": len(model.get("equipment") or []),
            "point_count": len(model.get("points") or []),
        },
    )
    return manifest


def mirror_site_ttl_from_edge(site_id: str, *, sync_edge: bool = True) -> dict[str, Any]:
    """Pull Turtle directly from Edge ``GET /api/model/ttl`` (legacy / parity path)."""
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    client = EdgeClient(site.base_url)

    edge_ttl_synced = False
    edge_ttl_error: str | None = None
    if sync_edge:
        try:
            client.api_post("/api/model/sync-ttl", {}, token=token)
            edge_ttl_synced = True
        except RuntimeError as exc:
            edge_ttl_error = str(exc)[:300]

    text = api_get_text(client.base_url, token, "/api/model/ttl?save=false", timeout=180)
    if not (text or "").strip():
        raise RuntimeError("Edge returned empty TTL — import model.json and sync TTL on Edge first")

    return _write_ttl(
        site_id,
        text,
        manifest_extra={
            "source": "edge_ttl",
            "source_url": f"{client.base_url}/api/model/ttl?save=false",
            "edge_ttl_synced": edge_ttl_synced,
            "edge_ttl_error": edge_ttl_error,
        },
    )


def ttl_mirror_status(site_id: str) -> dict[str, Any]:
    path = site_ttl_path(site_id)
    manifest_path = site_ttl_manifest_path(site_id)
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                manifest = raw
        except json.JSONDecodeError:
            manifest = {"parse_error": True}
    return {
        "site_id": site_id,
        "ttl_exists": path.is_file(),
        "ttl_path": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "manifest": manifest,
    }
