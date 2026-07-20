"""Thin HTTP client for openfdd-central (package ingest, dataset delete, SQL FDD).

Auth (BUG-1): when central has ``OPENFDD_JWT_SECRET``, attach Bearer via:

1. ``OPENFDD_API_TOKEN`` / ``OPENFDD_JWT`` — pre-minted service token, or
2. ``OPENFDD_UI_USERNAME`` + ``OPENFDD_UI_PASSWORD`` (defaults: admin +
   ``OPENFDD_ADMIN_PASSWORD``) — login to ``POST /api/auth/login`` and cache JWT.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

DEFAULT_API_BASE = "http://127.0.0.1:8080"

# UI cookbook / pandas keys → SQL registry parameter keys (BUG-3).
# Special mapped values: "_fan_hi_to_eps_vfd".
_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "VAV-1": {
        "zone_lo": "zone_t_lo",
        "zone_hi": "zone_t_hi",
    },
    "FC1": {
        "duct_static_err": "eps_dsp",
        # fan_hi is "fan at/above this frac" → SQL eps_vfd_spd = 1 - fan_hi
        "fan_hi": "_fan_hi_to_eps_vfd",
    },
    "SV-SPIKE": {
        "spike_scale_temperature": "spike_scale",
        "spike_scale_humidity": "spike_scale",
        "spike_scale_pressure": "spike_scale",
    },
}

_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_token_exp: float = 0.0


def api_base() -> str:
    return (os.environ.get("OPENFDD_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _env_token() -> str | None:
    for key in ("OPENFDD_API_TOKEN", "OPENFDD_JWT", "OPENFDD_UI_TOKEN"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


def _login_credentials() -> tuple[str, str] | None:
    user = (os.environ.get("OPENFDD_UI_USERNAME") or "admin").strip()
    password = (
        os.environ.get("OPENFDD_UI_PASSWORD")
        or os.environ.get("OPENFDD_ADMIN_PASSWORD")
        or ""
    ).strip()
    if not password:
        return None
    return user, password


def _fetch_login_token(timeout: float = 15.0) -> str | None:
    creds = _login_credentials()
    if not creds:
        return None
    user, password = creds
    try:
        resp = requests.post(
            f"{api_base()}/api/auth/login",
            json={"username": user, "password": password},
            timeout=timeout,
        )
        body = resp.json() if resp.content else {}
    except requests.RequestException:
        return None
    if not isinstance(body, dict):
        return None
    token = body.get("access_token") or body.get("token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def clear_auth_cache() -> None:
    global _cached_token, _cached_token_exp
    with _token_lock:
        _cached_token = None
        _cached_token_exp = 0.0


def bearer_token(*, force_refresh: bool = False) -> str | None:
    """Resolve Bearer token for central API calls (env token preferred, else login)."""
    global _cached_token, _cached_token_exp
    env = _env_token()
    if env:
        return env
    now = time.time()
    with _token_lock:
        if (
            not force_refresh
            and _cached_token
            and _cached_token_exp > now + 60
        ):
            return _cached_token
    token = _fetch_login_token()
    if not token:
        return None
    with _token_lock:
        _cached_token = token
        # Login mints ~8h tokens; refresh early.
        _cached_token_exp = now + 7 * 3600
        return _cached_token


def _auth_headers() -> dict[str, str]:
    token = bearer_token()
    if not token or token == "open":
        return {}
    return {"Authorization": f"Bearer {token}"}


def _merge_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(_auth_headers())
    if extra:
        headers.update(extra)
    return headers


def _request(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    retry_on_401: bool = True,
    **kwargs: Any,
) -> requests.Response:
    hdrs = _merge_headers(headers)
    resp = requests.request(method, url, headers=hdrs, timeout=timeout, **kwargs)
    if resp.status_code == 401 and retry_on_401 and not _env_token():
        clear_auth_cache()
        bearer_token(force_refresh=True)
        hdrs = _merge_headers(headers)
        resp = requests.request(method, url, headers=hdrs, timeout=timeout, **kwargs)
    return resp


def normalize_rule_params(rule_id: str, params: dict[str, float]) -> dict[str, float]:
    """Map UI / cookbook slider keys onto SQL registry parameter keys."""
    aliases = _PARAM_ALIASES.get(rule_id, {})
    out: dict[str, float] = {}

    for key, value in params.items():
        if key == "confirm_min":
            continue
        out[key] = float(value)

    # UI stores confirm_min (minutes); SQL registry uses confirm_seconds.
    if "confirm_seconds" not in out and "confirm_min" in params:
        out["confirm_seconds"] = float(params["confirm_min"]) * 60.0

    for ui_key, mapped in aliases.items():
        if ui_key not in params:
            continue
        if mapped == "_fan_hi_to_eps_vfd":
            if "eps_vfd_spd" not in params:
                out["eps_vfd_spd"] = max(0.0, min(1.0, 1.0 - float(params[ui_key])))
            out.pop("fan_hi", None)
            continue
        if mapped not in params:
            out[mapped] = float(params[ui_key])
        out.pop(ui_key, None)
    return out


def normalize_params_payload(
    params: dict[str, dict[str, float]] | None,
) -> dict[str, dict[str, float]] | None:
    if not params:
        return None
    return {rid: normalize_rule_params(rid, dict(p)) for rid, p in params.items() if p}


def _parse_json_response(resp: requests.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": f"central HTTP {resp.status_code}: {resp.text[:400]}"}
    if not isinstance(body, dict):
        return {"ok": False, "error": f"unexpected central response: {body!r}"}
    if resp.status_code == 401:
        body = {
            **body,
            "ok": False,
            "error": body.get("error")
            or "Authorization: Bearer <token> required "
            "(set OPENFDD_API_TOKEN or OPENFDD_ADMIN_PASSWORD for the UI)",
            "auth_required": True,
        }
    elif resp.status_code >= 400 and "ok" not in body:
        body = {**body, "ok": False, "error": body.get("error") or f"HTTP {resp.status_code}"}
    return body


def post_package_zip(zip_bytes: bytes, filename: str = "package.zip", timeout: float = 600.0) -> dict[str, Any]:
    """POST raw zip to /api/csv/import/package. Returns JSON body (ok/error)."""
    url = f"{api_base()}/api/csv/import/package"
    try:
        resp = _request(
            "POST",
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
    return _parse_json_response(resp)


def delete_dataset(dataset_id: str, timeout: float = 60.0) -> dict[str, Any]:
    """DELETE /api/datasets?id=… (Haystack / building id)."""
    did = (dataset_id or "").strip()
    if not did:
        return {"ok": False, "error": "dataset id required"}
    url = f"{api_base()}/api/datasets"
    try:
        resp = _request("DELETE", url, params={"id": did}, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"central unreachable ({api_base()}): {exc}", "central_down": True}
    return _parse_json_response(resp)


def list_datasets(timeout: float = 30.0) -> dict[str, Any]:
    try:
        resp = _request("GET", f"{api_base()}/api/datasets", timeout=timeout)
        return _parse_json_response(resp) if resp.ok or resp.status_code == 401 else {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
        }
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
    normalized = normalize_params_payload(params)
    if normalized:
        payload["params"] = normalized
    if equipment_id:
        payload["equipment_id"] = equipment_id
    try:
        resp = _request(
            "POST",
            f"{api_base()}/api/fdd/run",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"central unreachable ({api_base()}): {exc}", "central_down": True}
    return _parse_json_response(resp)


def fdd_results(timeout: float = 60.0) -> dict[str, Any]:
    try:
        resp = _request("GET", f"{api_base()}/api/fdd/results", timeout=timeout)
        return _parse_json_response(resp) if resp.ok or resp.status_code == 401 else {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
        }
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


def auth_status(timeout: float = 5.0) -> dict[str, Any]:
    try:
        resp = requests.get(f"{api_base()}/api/auth/status", timeout=timeout)
        body = resp.json() if resp.content else {}
        return body if isinstance(body, dict) else {"ok": False}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "central_down": True}
