"""Proxy RCx report APIs to OpenFDD Edge (read-only)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient


def _client_for(site_id: str) -> tuple[Any, str, EdgeClient]:
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    return site, token, EdgeClient(site.base_url)


def rcx_workspace(
    site_id: str,
    *,
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    show_fault_overlays: bool = True,
) -> dict[str, Any]:
    _site, token, client = _client_for(site_id)
    return client.get_rcx_workspace(
        site_id,
        hours=hours,
        start=start,
        end=end,
        show_fault_overlays=show_fault_overlays,
        token=token,
    )


def rcx_points(site_id: str, *, limit: int = 500) -> dict[str, Any]:
    _site, token, client = _client_for(site_id)
    return client.get_rcx_points(site_id, limit=limit, token=token)


def rcx_point_tree(site_id: str, *, limit: int = 500) -> dict[str, Any]:
    _site, token, client = _client_for(site_id)
    return client.get_rcx_point_tree(site_id, limit=limit, token=token)


def rcx_preview(site_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _site, token, client = _client_for(site_id)
    payload = {**body, "site_id": site_id}
    return client.post_rcx_preview(payload, token=token)


def rcx_report(site_id: str, body: dict[str, Any]) -> tuple[bytes, str]:
    _site, token, client = _client_for(site_id)
    payload = {**body, "site_id": site_id}
    return client.post_rcx_generate(payload, token=token)


def rcx_mechanical_summary(site_id: str, *, hours: int = 24) -> dict[str, Any]:
    preview = rcx_preview(
        site_id,
        {
            "hours": hours,
            "include_previews": False,
            "catalog_only": False,
        },
    )
    mech = preview.get("mechanical_summary") if isinstance(preview.get("mechanical_summary"), dict) else {}
    if not mech:
        mech = {"site_id": site_id}
    return mech


def rcx_mechanical_narrative(site_id: str, *, fast: bool = False) -> dict[str, Any]:
    preview = rcx_preview(
        site_id,
        {
            "catalog_only": True,
            "include_previews": False,
            "gallery_mode": fast,
        },
    )
    mech = preview.get("mechanical_summary") if isinstance(preview.get("mechanical_summary"), dict) else {}
    return {
        "site_id": site_id,
        "narrative": mech.get("narrative"),
        "counts": mech.get("counts"),
        "fast_mode": fast,
    }
