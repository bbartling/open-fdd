"""Proxy to local bacnet_toolshed commission agent (127.0.0.1:8767)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8767"


def commission_base_url() -> str:
    return os.environ.get("OPENFDD_BACNET_COMMISSION_URL", DEFAULT_URL).rstrip("/")


def commission_token() -> str:
    return os.environ.get("OPENFDD_BACNET_COMMISSION_TOKEN", "").strip()


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> tuple[int, Any]:
    url = f"{commission_base_url()}{path}"
    headers = {"Accept": "application/json"}
    token = commission_token()
    if token:
        headers["X-Commission-Token"] = token
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if timeout is None:
        timeout = 30.0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw.strip() else {}
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {"error": raw or exc.reason}
        except json.JSONDecodeError:
            payload = {"error": raw or str(exc)}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 503, {
            "error": "commission agent unreachable",
            "detail": str(exc.reason),
            "url": url,
        }


def commission_health(*, timeout: float | None = None) -> tuple[int, Any]:
    return _request("GET", "/api/health", timeout=timeout)


def commission_status() -> tuple[int, Any]:
    return _request("GET", "/api/status")


def start_discover(range_low: int | None, range_high: int | None) -> tuple[int, Any]:
    body: dict[str, Any] = {}
    if range_low is not None:
        body["range_low"] = str(range_low)
    if range_high is not None:
        body["range_high"] = str(range_high)
    return _request("POST", "/api/jobs/discover", body)


def whois(range_low: int, range_high: int) -> tuple[int, Any]:
    return _request(
        "POST",
        "/api/bacnet/whois",
        {"range_low": range_low, "range_high": range_high},
    )


def start_point_discovery(device_instance: int, device_address: str = "") -> tuple[int, Any]:
    body: dict[str, Any] = {"device_instance": device_instance}
    if device_address.strip():
        body["device_address"] = device_address.strip()
    return _request(
        "POST",
        "/api/jobs/point-discovery",
        body,
    )


def start_supervisory_check(device_instance: int, device_address: str = "") -> tuple[int, Any]:
    body: dict[str, Any] = {"device_instance": device_instance}
    if device_address.strip():
        body["device_address"] = device_address.strip()
    return _request("POST", "/api/jobs/supervisory-check", body)


def commission_override_status() -> tuple[int, Any]:
    return _request("GET", "/api/bacnet/overrides/status")


def commission_override_scan_once() -> tuple[int, Any]:
    return _request("POST", "/api/bacnet/overrides/scan-once", {}, timeout=60.0)


def bacnet_write(
    device_instance: int,
    object_identifier: str,
    property_identifier: str,
    value: Any,
    priority: int | None = None,
) -> tuple[int, Any]:
    body: dict[str, Any] = {
        "device_instance": device_instance,
        "object_identifier": object_identifier,
        "property_identifier": property_identifier,
        "value": value,
    }
    if priority is not None:
        body["priority"] = priority
    return _request("POST", "/api/bacnet/write", body)


def bacnet_read(
    device_instance: int,
    object_identifier: str,
    property_identifier: str = "present-value",
    device_address: str = "",
) -> tuple[int, Any]:
    body: dict[str, Any] = {
        "device_instance": device_instance,
        "object_identifier": object_identifier,
        "property_identifier": property_identifier,
    }
    if device_address.strip():
        body["device_address"] = device_address.strip()
    return _request("POST", "/api/bacnet/read", body)


def bacnet_read_multiple(
    device_instance: int,
    requests: list[dict[str, str]],
    device_address: str = "",
) -> tuple[int, Any]:
    body: dict[str, Any] = {"device_instance": device_instance, "requests": requests}
    if device_address.strip():
        body["device_address"] = device_address.strip()
    return _request("POST", "/api/bacnet/read-multiple", body)


def bacnet_priority_array(
    device_instance: int,
    object_identifier: str,
    device_address: str = "",
) -> tuple[int, Any]:
    body: dict[str, Any] = {
        "device_instance": device_instance,
        "object_identifier": object_identifier,
    }
    if device_address.strip():
        body["device_address"] = device_address.strip()
    return _request("POST", "/api/bacnet/priority-array", body)


def server_points() -> tuple[int, Any]:
    return _request("GET", "/api/bacnet/server/points")


def get_job(job_id: str) -> tuple[int, Any]:
    return _request("GET", f"/api/jobs/{job_id}")


def commission_poll_once() -> tuple[int, Any]:
    return _request("POST", "/api/bacnet/poll/once", {})


def commission_poll_status(*, timeout: float | None = None) -> tuple[int, Any]:
    return _request("GET", "/api/bacnet/poll/status", timeout=timeout)


def commission_poll_status_quick() -> tuple[int, Any]:
    """Non-blocking health probe while the poll loop holds the BACnet stack."""
    return commission_poll_status(timeout=2.0)
