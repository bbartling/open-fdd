"""HTTP JSON API client for OT-style REST polling (GET/POST)."""

from __future__ import annotations

import base64
import json
from typing import Any, Literal

import httpx
from urllib.parse import urlparse

MethodLiteral = Literal["GET", "POST"]
AuthTypeLiteral = Literal["none", "bearer", "basic"]
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


def _truthy(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return default


def _normalize_auth_type(value: Any) -> AuthTypeLiteral:
    text = str(value or "none").strip().lower()
    if text in {"bearer", "token", "api_key", "apikey"}:
        return "bearer"
    if text in {"basic", "http_basic"}:
        return "basic"
    return "none"


def _build_request_auth(payload: dict[str, Any]) -> tuple[dict[str, str], Any, bool]:
    """Return (headers, httpx_auth, verify_tls) for an outbound JSON API call."""
    headers: dict[str, str] = {}
    raw_headers = payload.get("headers")
    if isinstance(raw_headers, dict):
        headers = {str(k): str(v) for k, v in raw_headers.items()}

    auth_type = _normalize_auth_type(payload.get("auth_type"))
    bearer_token = str(payload.get("bearer_token") or payload.get("auth_token") or "").strip()
    basic_user = str(payload.get("basic_user") or payload.get("auth_user") or "").strip()
    basic_password = str(payload.get("basic_password") or payload.get("auth_password") or "")

    if auth_type == "bearer" and bearer_token:
        headers.setdefault("Authorization", f"Bearer {bearer_token}")
    elif auth_type == "basic" and basic_user:
        token = base64.b64encode(f"{basic_user}:{basic_password}".encode("utf-8")).decode("ascii")
        headers.setdefault("Authorization", f"Basic {token}")

    httpx_auth = None
    if auth_type == "basic" and basic_user:
        httpx_auth = (basic_user, basic_password)

    verify_tls = _truthy(payload.get("verify_tls"), default=True)
    return headers, httpx_auth, verify_tls


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
    headers, httpx_auth, verify_tls = _build_request_auth(payload)
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
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=verify_tls,
            auth=httpx_auth,
        ) as client:
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
