"""Thin HTTP client for openfdd-central (package ingest, dataset delete, SQL FDD)."""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_API_BASE = "http://127.0.0.1:8080"


def api_base() -> str:
    return (os.environ.get("OPENFDD_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def post_package_zip(zip_bytes: bytes, filename: str = "package.zip", timeout: float = 600.0) -> dict[str, Any]:
    """POST raw zip to /api/csv/import/package. Returns JSON body (ok/error)."""
    url = f"{api_base()}/api/csv/import/package"
    try:
        resp = requests.post(
            url,
            data=zip_bytes,
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"central unreachable ({api_base()}): {exc}", "central_down": True}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": f"central HTTP {resp.status_code}: {resp.text[:400]}"}
    if not isinstance(body, dict):
        return {"ok": False, "error": f"unexpected central response: {body!r}"}
    if resp.status_code >= 400 and "ok" not in body:
        body = {**body, "ok": False, "error": body.get("error") or f"HTTP {resp.status_code}"}
    return body


def delete_dataset(dataset_id: str, timeout: float = 60.0) -> dict[str, Any]:
    """DELETE /api/datasets?id=… (Haystack / building id)."""
    did = (dataset_id or "").strip()
    if not did:
        return {"ok": False, "error": "dataset id required"}
    url = f"{api_base()}/api/datasets"
    try:
        resp = requests.delete(url, params={"id": did}, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"central unreachable ({api_base()}): {exc}", "central_down": True}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": f"central HTTP {resp.status_code}: {resp.text[:400]}"}
    if not isinstance(body, dict):
        return {"ok": False, "error": f"unexpected central response: {body!r}"}
    return body


def list_datasets(timeout: float = 30.0) -> dict[str, Any]:
    try:
        resp = requests.get(f"{api_base()}/api/datasets", timeout=timeout)
        return resp.json() if resp.ok else {"ok": False, "error": f"HTTP {resp.status_code}"}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "central_down": True}


def run_fdd(
    *,
    rule_ids: list[str] | None = None,
    params: dict[str, dict[str, float]] | None = None,
    equipment_id: str | None = None,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """POST /api/fdd/run — DataFusion SQL registry engine (no pandas)."""
    payload: dict[str, Any] = {"mode": "registry"}
    if rule_ids:
        payload["rule_ids"] = list(rule_ids)
    if params:
        payload["params"] = params
    if equipment_id:
        payload["equipment_id"] = equipment_id
    try:
        resp = requests.post(
            f"{api_base()}/api/fdd/run",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"central unreachable ({api_base()}): {exc}", "central_down": True}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": f"central HTTP {resp.status_code}: {resp.text[:400]}"}
    if not isinstance(body, dict):
        return {"ok": False, "error": f"unexpected central response: {body!r}"}
    return body


def fdd_results(timeout: float = 60.0) -> dict[str, Any]:
    try:
        resp = requests.get(f"{api_base()}/api/fdd/results", timeout=timeout)
        return resp.json() if resp.ok else {"ok": False, "error": f"HTTP {resp.status_code}"}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "central_down": True}


def health_ok(timeout: float = 3.0) -> bool:
    try:
        r = requests.get(f"{api_base()}/api/health", timeout=timeout)
        if r.status_code != 200:
            return False
        data = r.json()
        return bool(data.get("ok", True))
    except Exception:
        return False
