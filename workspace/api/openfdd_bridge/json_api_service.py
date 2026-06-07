"""HTTP JSON API client for OT-style REST polling (GET/POST)."""

from __future__ import annotations

import json
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

MethodLiteral = Literal["GET", "POST"]
MAX_BODY_BYTES = 64_000


class JsonApiServiceError(ValueError):
    """Invalid request or HTTP failure."""


def _extract_json_path(data: Any, path: str) -> Any:
    text = str(path or "").strip()
    if not text:
        if isinstance(data, (dict, list)):
            return json.dumps(data, default=str)[:500]
        return data
    cur: Any = data
    for part in text.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)[:500]
    return str(value)


def execute_json_api_request(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise JsonApiServiceError("url required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise JsonApiServiceError("url must use http or https")
    if not parsed.netloc:
        raise JsonApiServiceError("url must include host")

    method = str(payload.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST"}:
        raise JsonApiServiceError(f"unsupported method: {method}")

    timeout = float(payload.get("timeout") or 5.0)
    json_path = str(payload.get("json_path") or "").strip()
    label = str(payload.get("label") or "").strip() or None
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    body_raw = payload.get("body")
    body: dict[str, Any] | None = None
    if body_raw is not None and body_raw != "":
        if isinstance(body_raw, dict):
            body = body_raw
        else:
            try:
                body = json.loads(str(body_raw))
            except json.JSONDecodeError as exc:
                raise JsonApiServiceError(f"invalid JSON body: {exc}") from exc
        if len(json.dumps(body, default=str)) > MAX_BODY_BYTES:
            raise JsonApiServiceError("request body too large")

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if method == "GET":
                resp = client.get(url, headers=headers)
            else:
                resp = client.post(url, headers=headers, json=body)
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "url": url,
            "method": method,
            "success": False,
            "status_code": None,
            "decoded": None,
            "raw_json": None,
            "label": label,
            "error": f"http_error: {exc}",
        }

    try:
        data = resp.json()
    except Exception:
        return {
            "ok": False,
            "url": url,
            "method": method,
            "success": False,
            "status_code": resp.status_code,
            "decoded": None,
            "raw_json": None,
            "label": label,
            "error": "response_not_json",
        }

    extracted = _extract_json_path(data, json_path)
    return {
        "ok": resp.is_success,
        "url": url,
        "method": method,
        "success": resp.is_success,
        "status_code": resp.status_code,
        "decoded": extracted,
        "present_value": _format_value(extracted),
        "raw_json": data,
        "json_path": json_path,
        "label": label,
        "error": None if resp.is_success else f"http_status_{resp.status_code}",
    }
