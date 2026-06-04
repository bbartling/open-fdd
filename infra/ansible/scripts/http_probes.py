#!/usr/bin/env python3
"""Shared HTTP probes for Open-FDD edge verification scripts."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


CADDY_WELCOME_MARKERS = (
    "Your web server is working",
    "Caddy is ready to serve your site",
    "Congratulations!",
)
OPENFDD_APP_MARKER = "Open-FDD Operator"


def fetch(url: str, *, timeout: float = 20.0, headers: dict[str, str] | None = None) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, body, hdrs
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, body, hdrs
    except TimeoutError as exc:
        raise RuntimeError(f"request timed out after {timeout}s") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _agent_fetch_timeout_s() -> float:
    raw = os.environ.get("OPENFDD_PROBE_AGENT_TIMEOUT_S", "45").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 45.0


def post_json(url: str, payload: dict[str, Any], *, timeout: float = 20.0, headers: dict[str, str] | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise RuntimeError(f"request timed out after {timeout}s") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise RuntimeError(f"request timed out after {timeout}s") from exc
        raise RuntimeError(str(reason)) from exc


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def is_caddy_welcome_page(html: str) -> bool:
    return any(m in html for m in CADDY_WELCOME_MARKERS)


def is_openfdd_dashboard_html(html: str) -> bool:
    return OPENFDD_APP_MARKER in html and 'id="root"' in html


def extract_asset_path(html: str) -> str:
    m = re.search(r'src="(/assets/[^"]+\.js)"', html)
    return m.group(1) if m else ""


def _stack_services(body: str) -> list[dict[str, Any]]:
    try:
        return json.loads(body).get("services", [])
    except json.JSONDecodeError:
        return []


PUBLIC_CHECK_ENGINE_PATHS = (
    "/api/faults/status",
    "/api/building/status",
    "/openfdd-agent/building-insight",
)


def check_integrator_ui_api(base: str, token: str, *, site_id: str = "demo") -> dict[str, Any]:
    """Authenticated probes for Rule Lab / Plot tabs (scope SPARQL + timeseries query coercion)."""
    out: dict[str, Any] = {"errors": [], "warnings": [], "site_id": site_id}
    headers = auth_headers(token)
    root = base.rstrip("/")

    scope_url = f"{root}/api/model/scope?site_id={site_id}"
    status, body, _ = fetch(scope_url, headers=headers)
    out["model_scope_status"] = status
    if status == 503:
        out["errors"].append(
            f"/api/model/scope HTTP 503 for site {site_id!r} — import model and Sync TTL (data_model.ttl missing?)"
        )
    elif status != 200:
        out["errors"].append(f"/api/model/scope HTTP {status}: {body[:200]}")
    else:
        try:
            payload = json.loads(body)
            equipment = payload.get("equipment") or []
            out["model_scope_equipment_count"] = len(equipment)
            if not equipment:
                out["errors"].append(f"/api/model/scope returned no equipment for site {site_id!r}")
            if payload.get("query_engine") != "sparql":
                out["warnings"].append(f"scope query_engine={payload.get('query_engine')!r}")
        except json.JSONDecodeError:
            out["errors"].append("/api/model/scope not JSON")

    cols = "5007-analog-input-1173,5007-analog-input-1192"
    readings_url = (
        f"{root}/api/timeseries/readings?site_id={site_id}&columns={cols}"
        "&hours=24&include_faults=false&rolling_avg_minutes=5&show_rolling_avg=true"
    )
    status, body, _ = fetch(readings_url, headers=headers)
    out["timeseries_readings_status"] = status
    if status == 422:
        out["errors"].append(
            "/api/timeseries/readings HTTP 422 — rolling_avg_minutes query validation failed "
            f"(body={body[:240]})"
        )
    elif status not in (200, 404):
        out["errors"].append(f"/api/timeseries/readings HTTP {status}: {body[:200]}")
    elif status == 404:
        out["warnings"].append("/api/timeseries/readings 404 — no feather data yet (poll may be warming up)")
    return out


def check_building_dashboard_health(
    base: str,
    token: str,
    *,
    site_id: str = "demo",
    poll_fresh_max_s: float = 180.0,
) -> dict[str, Any]:
    """Detect false offline poll_health alerts and feather lag while BACnet poll is live."""
    out: dict[str, Any] = {"errors": [], "warnings": [], "site_id": site_id}
    headers = auth_headers(token)
    root = base.rstrip("/")

    poll_url = f"{root}/api/bacnet/poll/status"
    try:
        poll_status, poll_body, _ = fetch(poll_url, headers=headers, timeout=_bacnet_fetch_timeout_s())
    except RuntimeError as exc:
        out["warnings"].append(f"building health: poll status unreachable: {exc}")
        return out
    poll_age_s: float | None = None
    if poll_status == 200:
        try:
            poll = json.loads(poll_body)
            at_raw = str(poll.get("at_utc") or poll.get("at") or "").strip()
            if at_raw:
                ts = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                poll_age_s = (datetime.now(timezone.utc) - ts).total_seconds()
                out["poll_age_seconds"] = round(poll_age_s, 1)
        except (json.JSONDecodeError, ValueError):
            pass

    faults_url = f"{root}/api/faults/status"
    try:
        f_status, f_body, _ = fetch(faults_url, headers=headers, timeout=30.0)
    except RuntimeError as exc:
        out["warnings"].append(f"building health: faults/status unreachable: {exc}")
        return out
    if f_status != 200:
        out["warnings"].append(f"/api/faults/status HTTP {f_status}")
        return out
    try:
        faults = json.loads(f_body)
    except json.JSONDecodeError:
        out["warnings"].append("/api/faults/status not JSON")
        return out

    families = faults.get("families") or []
    poll_offline = 0
    poll_historian = 0
    bld_d_badges = 0
    for fam in families:
        if not isinstance(fam, dict):
            continue
        for alert in fam.get("faults") or []:
            if not isinstance(alert, dict):
                continue
            src = str(alert.get("source") or "")
            title = str(alert.get("title") or "")
            if alert.get("code") == "BLD-D" and src in {"poll_health", "model_health"}:
                bld_d_badges += 1
            if src != "poll_health":
                continue
            if "device offline" in title.lower():
                poll_offline += 1
            if "historian behind" in title.lower():
                poll_historian += 1
    out["poll_health_offline_alerts"] = poll_offline
    out["poll_health_historian_lag_alerts"] = poll_historian
    if bld_d_badges:
        out["errors"].append(
            f"Dashboard shows {bld_d_badges} poll/model alert(s) with BLD-D code badge "
            "(should show device names only)"
        )
    if poll_age_s is not None and poll_age_s <= poll_fresh_max_s and poll_offline >= 3:
        out["errors"].append(
            f"False offline: {poll_offline} poll_health 'device offline' alerts while BACnet poll "
            f"is fresh ({int(poll_age_s)}s ago) — check feather ingest"
        )
    if poll_historian:
        out["warnings"].append(
            f"{poll_historian} device(s) historian behind live poll — bridge ingest may be slow"
        )

    scope_url = f"{root}/api/model/scope?site_id={site_id}"
    try:
        scope_status, scope_body, _ = fetch(scope_url, headers=headers, timeout=60.0)
        out["model_scope_status"] = scope_status
        if scope_status == 503:
            out["errors"].append(f"/api/model/scope HTTP 503 for site {site_id!r} (Rule Lab / plots broken)")
    except RuntimeError as exc:
        out["warnings"].append(f"model scope probe failed: {exc}")

    return out


def check_public_check_engine(base: str) -> dict[str, Any]:
    """Anonymous read probes for home / faults traffic-light UI (no Bearer token)."""
    out: dict[str, Any] = {"errors": [], "warnings": [], "endpoints": {}}
    root = base.rstrip("/")
    for path in PUBLIC_CHECK_ENGINE_PATHS:
        url = f"{root}{path}"
        status, body, _ = fetch(url)
        out["endpoints"][path] = status
        if status == 401:
            out["errors"].append(f"{path} HTTP 401 — check-engine dashboard must not require login")
        elif status != 200:
            out["errors"].append(f"{path} HTTP {status}")
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            out["errors"].append(f"{path} not JSON")
            continue
        if path == "/openfdd-agent/building-insight":
            if not (payload.get("sentence") or payload.get("ok")):
                out["warnings"].append("/openfdd-agent/building-insight empty sentence")
        elif path in ("/api/faults/status", "/api/building/status"):
            if not payload.get("ok", True) and "traffic" not in payload:
                out["warnings"].append(f"{path} unexpected payload shape")
    return out


def check_entry(
    base: str,
    *,
    require_mcp: bool = True,
    require_ollama: bool = False,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Probe LAN entry: health, dashboard HTML, JS bundle, stack services."""
    out: dict[str, Any] = {"base": base, "errors": [], "warnings": []}
    health_url = f"{base.rstrip('/')}/health"
    status, body, _ = fetch(health_url)
    out["health_status"] = status
    if status != 200:
        out["errors"].append(f"/health HTTP {status}")
    else:
        try:
            payload = json.loads(body)
            if not payload.get("ok"):
                out["errors"].append("/health ok!=true")
            if payload.get("service") != "openfdd-bridge":
                out["errors"].append(f"/health service={payload.get('service')!r}")
            out["auth_required"] = payload.get("auth_required")
        except json.JSONDecodeError:
            out["errors"].append("/health not JSON")

    root_url = f"{base.rstrip('/')}/"
    status, html, _ = fetch(root_url)
    out["root_status"] = status
    if status != 200:
        out["errors"].append(f"/ HTTP {status}")
    elif is_caddy_welcome_page(html):
        out["errors"].append("Caddy default welcome page at / (reverse_proxy not active)")
    elif not is_openfdd_dashboard_html(html):
        out["errors"].append('missing Open-FDD React shell (title/id="root")')

    asset = extract_asset_path(html) if status == 200 else ""
    out["asset_path"] = asset
    if asset:
        a_status, _, _ = fetch(f"{base.rstrip('/')}{asset}")
        out["asset_status"] = a_status
        if a_status != 200:
            out["errors"].append(f"dashboard asset {asset} HTTP {a_status}")
    elif status == 200 and not is_caddy_welcome_page(html):
        out["errors"].append("no /assets/*.js in dashboard HTML")

    stack_url = f"{base.rstrip('/')}/health/stack"
    stack_headers = headers if headers else None
    status, body, _ = fetch(stack_url, headers=stack_headers)
    out["stack_status"] = status
    out["stack_services"] = {}
    if status == 401:
        if not stack_headers:
            out["warnings"].append("/health/stack HTTP 401 without auth (expected — use integrator login)")
        else:
            out["errors"].append("/health/stack HTTP 401 with Bearer token")
    elif status != 200:
        out["errors"].append(f"/health/stack HTTP {status}")
    else:
        services = _stack_services(body)
        for svc in services:
            sid = svc.get("id")
            if sid:
                out["stack_services"][sid] = svc
        bridge = out["stack_services"].get("bridge", {})
        if bridge.get("status") not in ("green", "yellow"):
            out["errors"].append(f"bridge stack status={bridge.get('status')}")
        mcp = out["stack_services"].get("mcp_rag", {})
        out["mcp_configured"] = mcp.get("configured")
        out["mcp_status"] = mcp.get("status")
        if require_mcp:
            if not mcp.get("configured"):
                out["errors"].append("MCP RAG not enabled on bridge (set OFDD_MCP_ENABLED=1)")
            elif mcp.get("status") not in ("green", "yellow"):
                out["errors"].append(f"MCP RAG stack status={mcp.get('status')} detail={mcp.get('detail')}")
        ollama_note = out["stack_services"].get("ollama")
        if require_ollama:
            pass  # checked via authenticated ollama health below

    return out


def check_login(base: str, username: str, password: str) -> dict[str, Any]:
    out: dict[str, Any] = {"username": username, "errors": [], "token": ""}
    url = f"{base.rstrip('/')}/api/auth/login"
    status, body = post_json(url, {"username": username, "password": password})
    out["login_status"] = status
    if status != 200:
        out["errors"].append(f"login HTTP {status}: {body[:200]}")
        return out
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        out["errors"].append("login response not JSON")
        return out
    if not payload.get("token"):
        out["errors"].append("login missing token")
    else:
        out["token"] = payload["token"]
    if not payload.get("username"):
        out["errors"].append("login missing username")
    return out


def _min_model_points() -> int:
    try:
        return max(0, int(os.environ.get("OPENFDD_HEALTH_MIN_MODEL_POINTS", "1")))
    except ValueError:
        return 1


def _min_model_equipment() -> int:
    try:
        return max(0, int(os.environ.get("OPENFDD_HEALTH_MIN_MODEL_EQUIPMENT", "0")))
    except ValueError:
        return 0


def _bacnet_fetch_timeout_s() -> float:
    raw = os.environ.get("OPENFDD_PROBE_BACNET_TIMEOUT_S", "60").strip()
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 60.0


def check_bacnet_driver(
    base: str,
    token: str,
    *,
    min_devices: int = 1,
    min_enabled_points: int = 1,
    max_poll_age_s: float | None = None,
) -> dict[str, Any]:
    """BACnet poll driver: device tree inventory + fresh poll samples."""
    out: dict[str, Any] = {"errors": [], "warnings": []}
    headers = auth_headers(token)
    root = base.rstrip("/")
    bacnet_to = _bacnet_fetch_timeout_s()
    if max_poll_age_s is None:
        raw = os.environ.get("OPENFDD_HEALTH_MAX_POLL_AGE_S", "900").strip()
        try:
            max_poll_age_s = float(raw)
        except ValueError:
            max_poll_age_s = 900.0

    tree_url = f"{root}/api/bacnet/driver/tree"
    try:
        status, body, _ = fetch(tree_url, headers=headers, timeout=bacnet_to)
    except RuntimeError as exc:
        out["errors"].append(f"/api/bacnet/driver/tree unreachable: {exc}")
        return out
    out["bacnet_tree_status"] = status
    if status != 200:
        out["errors"].append(f"/api/bacnet/driver/tree HTTP {status}: {body[:200]}")
        return out
    try:
        tree = json.loads(body)
    except json.JSONDecodeError:
        out["errors"].append("/api/bacnet/driver/tree not JSON")
        return out

    devices = tree.get("devices") or []
    out["bacnet_device_count"] = len(devices)
    out["bacnet_inventory_source"] = tree.get("inventory_source") or ""
    enabled = sum(int(d.get("poll_count") or 0) for d in devices)
    out["bacnet_enabled_points"] = enabled
    if len(devices) < min_devices:
        out["errors"].append(
            f"BACnet driver tree has {len(devices)} device(s) (need >={min_devices}); "
            "points_discovered.csv may be missing on edge — run edge_site_backup then redeploy"
        )
    if enabled < min_enabled_points:
        out["errors"].append(
            f"BACnet driver has {enabled} enabled point(s) in tree (need >={min_enabled_points})"
        )
    if out["bacnet_inventory_source"] == "empty":
        out["errors"].append("BACnet inventory_source=empty (no points.csv / points_discovered.csv)")

    poll_url = f"{root}/api/bacnet/poll/status"
    try:
        status, body, _ = fetch(poll_url, headers=headers, timeout=bacnet_to)
    except RuntimeError as exc:
        out["errors"].append(f"/api/bacnet/poll/status unreachable: {exc}")
        return out
    out["bacnet_poll_status"] = status
    if status != 200:
        out["errors"].append(f"/api/bacnet/poll/status HTTP {status}: {body[:200]}")
        return out
    try:
        poll = json.loads(body)
    except json.JSONDecodeError:
        out["errors"].append("/api/bacnet/poll/status not JSON")
        return out

    out["poll_enabled_points"] = poll.get("enabled_points")
    out["poll_samples"] = poll.get("samples")
    out["poll_at_utc"] = poll.get("at_utc") or poll.get("at")
    out["poll_at_local_display"] = poll.get("at_local_display")
    out["poll_site_timezone"] = poll.get("site_timezone")
    poll_err = str(poll.get("error") or "").strip()
    if poll_err:
        out["errors"].append(f"BACnet poll driver error: {poll_err}")

    at_raw = str(poll.get("at_utc") or poll.get("at") or "").strip()
    if not at_raw and enabled >= min_enabled_points:
        out["warnings"].append("BACnet poll enabled but no last sample timestamp yet")
    elif at_raw:
        try:
            ts = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - ts).total_seconds()
            out["poll_age_seconds"] = round(age_s, 1)
            if max_poll_age_s > 0 and age_s > max_poll_age_s:
                out["errors"].append(
                    f"BACnet poll last sample {int(age_s)}s old (max {int(max_poll_age_s)}s); "
                    f"UTC {at_raw}"
                )
        except ValueError:
            out["warnings"].append(f"Could not parse poll timestamp: {at_raw!r}")

    comm_url = f"{root}/api/bacnet/commission/status"
    try:
        comm_status, _body, _ = fetch(comm_url, headers=headers, timeout=bacnet_to)
        out["bacnet_commission_status"] = comm_status
        if comm_status not in (200, 503):
            out["warnings"].append(f"/api/bacnet/commission/status HTTP {comm_status}")
    except RuntimeError as exc:
        out["warnings"].append(f"/api/bacnet/commission/status skipped: {exc}")
    return out


def check_model_sparql_health(base: str, token: str) -> dict[str, Any]:
    """BRICK data model health: JSON summary + SPARQL tree/graph over synced TTL."""
    out: dict[str, Any] = {"errors": [], "warnings": []}
    headers = auth_headers(token)
    root = base.rstrip("/")
    min_points = _min_model_points()
    min_equipment = _min_model_equipment()

    sites_url = f"{root}/api/model/sites"
    status, body, _ = fetch(sites_url, headers=headers)
    out["model_sites_status"] = status
    site_id = ""
    if status != 200:
        out["errors"].append(f"/api/model/sites HTTP {status}")
    else:
        try:
            sites_payload = json.loads(body)
            site_id = str(sites_payload.get("active_site_id") or "").strip()
            if not site_id:
                sites = sites_payload.get("sites") or []
                if sites and isinstance(sites[0], dict):
                    site_id = str(sites[0].get("site_id") or "").strip()
            out["active_site_id"] = site_id
            if not site_id:
                out["errors"].append("no active BRICK site_id from /api/model/sites")
        except json.JSONDecodeError:
            out["errors"].append("/api/model/sites not JSON")

    health_url = f"{root}/api/model/health"
    status, body, _ = fetch(health_url, headers=headers)
    out["model_health_status"] = status
    if status != 200:
        out["errors"].append(f"/api/model/health HTTP {status}")
    else:
        try:
            health = json.loads(body)
            out["model_configured"] = health.get("configured")
            out["model_health_score"] = health.get("score")
            out["model_health_status_label"] = health.get("status")
            out["ttl_exists"] = health.get("ttl_exists")
            out["ttl_path"] = health.get("ttl_path")
            counts = health.get("counts") or {}
            if isinstance(counts, dict):
                out["model_site_count"] = counts.get("sites")
                out["model_equipment_count_json"] = counts.get("equipment")
                out["model_point_count_json"] = counts.get("points")
            if not health.get("ttl_exists"):
                out["errors"].append(
                    "data_model.ttl missing — import model.json then POST /api/model/sync-ttl"
                )
            if health.get("configured") is False:
                out["errors"].append("BRICK model empty (no sites, equipment, or points in model.json)")
            if str(health.get("status") or "") == "critical":
                out["errors"].append(
                    f"model health critical (score={health.get('score')}); fix orphans in Data Model tab"
                )
            critical_issues = [
                i for i in (health.get("issues") or []) if isinstance(i, dict) and i.get("severity") == "critical"
            ]
            if critical_issues:
                out["errors"].append(
                    f"model has {len(critical_issues)} critical issue(s): {critical_issues[0].get('title', '')}"
                )
        except json.JSONDecodeError:
            out["errors"].append("/api/model/health not JSON")

    tree_url = f"{root}/api/model/tree"
    status, body, _ = fetch(tree_url, headers=headers)
    out["model_tree_status"] = status
    if status != 200:
        detail = ""
        if status == 503:
            try:
                detail = json.loads(body).get("detail", "")
            except json.JSONDecodeError:
                detail = body[:200]
            if detail:
                out["errors"].append(f"/api/model/tree HTTP 503: {detail}")
            else:
                out["errors"].append(f"/api/model/tree HTTP {status}")
        else:
            out["errors"].append(f"/api/model/tree HTTP {status}")
    else:
        try:
            payload = json.loads(body)
            points = payload.get("points") or []
            out["model_point_count"] = len(points)
            out["model_equipment_count_tree"] = len(payload.get("equipment") or [])
            engine = payload.get("query_engine") or ""
            out["model_query_engine"] = engine
            if engine != "sparql":
                out["errors"].append(f"/api/model/tree query_engine={engine!r} (expected sparql)")
            if len(points) < min_points:
                out["errors"].append(
                    f"SPARQL model tree has {len(points)} point(s) (need >={min_points})"
                )
        except json.JSONDecodeError:
            out["errors"].append("/api/model/tree not JSON")

    if site_id:
        graph_qs = urllib.parse.urlencode({"site_id": site_id})
        graph_url = f"{root}/api/model/graph?{graph_qs}"
        status, body, _ = fetch(graph_url, headers=headers)
        out["model_graph_status"] = status
        if status != 200:
            detail = ""
            if status == 503:
                try:
                    detail = json.loads(body).get("detail", "")
                except json.JSONDecodeError:
                    detail = body[:200]
                out["errors"].append(f"/api/model/graph HTTP 503: {detail or 'sync TTL'}")
            else:
                out["errors"].append(f"/api/model/graph HTTP {status}")
        else:
            try:
                gpayload = json.loads(body)
                if gpayload.get("query_engine") != "sparql":
                    out["errors"].append(
                        f"/api/model/graph query_engine={gpayload.get('query_engine')!r} (expected sparql)"
                    )
                equipment = gpayload.get("equipment") or []
                out["model_equipment_count"] = len(equipment)
                if len(equipment) < min_equipment:
                    out["errors"].append(
                        f"SPARQL site graph has {len(equipment)} equipment (need >={min_equipment})"
                    )
            except json.JSONDecodeError:
                out["errors"].append("/api/model/graph not JSON")

    if os.environ.get("OPENFDD_HEALTH_PROBE_BACNET_SYNC", "").strip().lower() in {"1", "true", "yes"}:
        sync_url = f"{root}/api/model/bacnet-sync"
        status, body, _ = fetch(sync_url, headers=headers)
        out["bacnet_sync_status"] = status
        if status != 200:
            out["warnings"].append(f"/api/model/bacnet-sync HTTP {status} (optional probe)")

    return out


def check_model_api(base: str, token: str) -> dict[str, Any]:
    """Authenticated BRICK / data-modeling API probes (SPARQL + model health)."""
    return check_model_sparql_health(base, token)


def check_agent_stack(
    base: str,
    token: str,
    *,
    require_ollama: bool = False,
    require_mcp: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {"errors": [], "warnings": []}
    headers = auth_headers(token)
    ctx_url = f"{base.rstrip('/')}/openfdd-agent/context"
    try:
        status, body, _ = fetch(ctx_url, headers=headers, timeout=_agent_fetch_timeout_s())
    except RuntimeError as exc:
        out["errors"].append(f"/openfdd-agent/context unreachable: {exc}")
        return out
    out["agent_context_status"] = status
    if status != 200:
        out["errors"].append(f"/openfdd-agent/context HTTP {status}")
        return out
    try:
        ctx = json.loads(body)
        mcp = ctx.get("mcp") or {}
        out["mcp_enabled_in_context"] = mcp.get("mcp_enabled")
        if not mcp.get("mcp_enabled"):
            msg = "agent context reports MCP disabled"
            if require_mcp:
                out["errors"].append(msg)
            else:
                out["warnings"].append(msg)
    except json.JSONDecodeError:
        out["errors"].append("/openfdd-agent/context not JSON")

    ollama_url = f"{base.rstrip('/')}/openfdd-agent/ollama/health"
    try:
        status, body, _ = fetch(ollama_url, headers=headers, timeout=15.0)
    except RuntimeError as exc:
        if require_ollama:
            out["errors"].append(f"/openfdd-agent/ollama/health unreachable: {exc}")
        else:
            out["warnings"].append(f"Ollama health probe skipped: {exc}")
        return out
    out["ollama_health_status"] = status
    if status == 200:
        try:
            oh = json.loads(body)
            out["ollama_reachable"] = oh.get("reachable") or oh.get("ok")
            out["ollama_model"] = oh.get("model") or oh.get("configured_model")
            if require_ollama and not out.get("ollama_reachable"):
                out["errors"].append(f"Ollama not reachable: {oh}")
        except json.JSONDecodeError:
            out["errors"].append("/openfdd-agent/ollama/health not JSON")
    elif require_ollama:
        out["errors"].append(f"/openfdd-agent/ollama/health HTTP {status}")
    else:
        out["warnings"].append("Ollama not running on edge (expected on Pi 3 armv7l)")

    return out


def check_ollama_hello_chat(base: str, token: str) -> dict[str, Any]:
    """Minimal agent chat to confirm Ollama returns a reply (no MCP keyword check)."""
    out: dict[str, Any] = {"errors": [], "warnings": []}
    headers = auth_headers(token)
    url = f"{base.rstrip('/')}/openfdd-agent/chat"
    status, body = post_json(
        url,
        {"message": "Reply with one short greeting word only.", "history": []},
        headers=headers,
        timeout=120.0,
    )
    out["chat_status"] = status
    if status != 200:
        out["errors"].append(f"ollama hello chat HTTP {status}: {body[:300]}")
        return out
    try:
        payload = json.loads(body)
        out["chat_ok"] = payload.get("ok")
        reply = str(payload.get("reply") or "").strip()
        out["reply_preview"] = reply[:240]
        if not payload.get("ok"):
            out["errors"].append(f"ollama hello chat failed: {payload.get('error') or body[:200]}")
        elif not reply:
            out["errors"].append("ollama hello chat returned empty reply")
    except json.JSONDecodeError:
        out["errors"].append("/openfdd-agent/chat not JSON (ollama hello)")
    return out


def check_agent_chat(
    base: str,
    token: str,
    *,
    message: str | None = None,
    require_mcp: bool = True,
) -> dict[str, Any]:
    """POST agent chat — validates Ollama path; reply should mention MCP when enabled."""
    out: dict[str, Any] = {"errors": [], "warnings": [], "skipped": False}
    if not require_mcp:
        out["skipped"] = True
        out["warnings"].append("agent chat probe skipped (--require-mcp not set)")
        return out
    headers = auth_headers(token)
    msg = message or (
        "In one sentence: is MCP RAG enabled on this bridge and what doc search URL would you use?"
    )
    url = f"{base.rstrip('/')}/openfdd-agent/chat"
    status, body = post_json(url, {"message": msg, "history": []}, headers=headers, timeout=120.0)
    out["chat_status"] = status
    if status != 200:
        out["errors"].append(f"/openfdd-agent/chat HTTP {status}: {body[:300]}")
        return out
    try:
        payload = json.loads(body)
        out["chat_ok"] = payload.get("ok")
        out["chat_mode"] = payload.get("mode")
        reply = str(payload.get("reply") or "").lower()
        out["reply_preview"] = (payload.get("reply") or "")[:240]
        if not payload.get("ok"):
            out["errors"].append(f"chat failed: {payload.get('error') or body[:200]}")
        elif "mcp" not in reply and "8090" not in reply and "search_docs" not in reply:
            out["warnings"].append("chat reply did not mention MCP (Ollama may be down or model ignored context)")
    except json.JSONDecodeError:
        out["errors"].append("/openfdd-agent/chat not JSON")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: http_probes.py check <base_url> [user pass] [--require-mcp] [--require-ollama] [--site-id SITE]\n"
            "       http_probes.py check-public <base_url>",
            file=sys.stderr,
        )
        return 2
    cmd = sys.argv[1]
    if cmd == "check-public":
        if len(sys.argv) < 3:
            print("usage: http_probes.py check-public <base_url>", file=sys.stderr)
            return 2
        result = check_public_check_engine(sys.argv[2])
        print(json.dumps(result, indent=2))
        return 0 if not result.get("errors") else 1
    if cmd == "check":
        args = sys.argv[2:]
        require_mcp = "--require-mcp" in args
        require_ollama = "--require-ollama" in args
        site_id = os.environ.get("OFDD_PROBE_SITE_ID", "demo")
        filtered: list[str] = []
        i = 0
        while i < len(args):
            if args[i] == "--site-id" and i + 1 < len(args):
                site_id = args[i + 1]
                i += 2
                continue
            if not args[i].startswith("--require-"):
                filtered.append(args[i])
            i += 1
        args = filtered
        base = args[0]
        if len(args) >= 3:
            login = check_login(base, args[1], args[2])
            result: dict[str, Any] = {"errors": [], "warnings": []}
            result["login"] = login
            result["errors"].extend(login.get("errors", []))
            auth_hdrs = auth_headers(login["token"]) if login.get("token") else None
            entry = check_entry(
                base,
                require_mcp=require_mcp,
                require_ollama=require_ollama,
                headers=auth_hdrs,
            )
            result.update(entry)
            result["errors"].extend(entry.get("errors", []))
            result["warnings"].extend(entry.get("warnings", []))
            if login.get("token"):
                def _run_probe(name: str, fn: Any) -> dict[str, Any]:
                    try:
                        return fn()
                    except RuntimeError as exc:
                        return {
                            "errors": [f"{name} probe failed: {exc}"],
                            "warnings": [],
                        }
                    except Exception as exc:  # noqa: BLE001 — keep deploy checks running
                        return {
                            "errors": [f"{name} probe failed: {exc}"],
                            "warnings": [],
                        }

                model = _run_probe("model_api", lambda: check_model_api(base, login["token"]))
                result["model_api"] = model
                result["errors"].extend(model.get("errors", []))
                result["warnings"].extend(model.get("warnings", []))
                agent = _run_probe(
                    "agent",
                    lambda: check_agent_stack(
                        base,
                        login["token"],
                        require_ollama=require_ollama,
                        require_mcp=require_mcp,
                    ),
                )
                result["agent"] = agent
                result["errors"].extend(agent.get("errors", []))
                result["warnings"].extend(agent.get("warnings", []))
                if require_mcp:
                    chat = _run_probe(
                        "agent_chat",
                        lambda: check_agent_chat(base, login["token"], require_mcp=require_mcp),
                    )
                    if chat.get("errors") and "skipped" not in chat:
                        chat.setdefault("warnings", []).append(
                            "agent chat probe had errors (Ollama may be off)"
                        )
                    result["agent_chat"] = chat
                    for chat_err in chat.get("errors", []):
                        low = str(chat_err).lower()
                        if any(x in low for x in ("timeout", "timed out", "slow", "ollama")):
                            result["warnings"].append(f"agent chat probe: {chat_err}")
                        else:
                            result["errors"].append(f"agent chat probe: {chat_err}")
                    result["warnings"].extend(chat.get("warnings", []))
                probe_site = site_id
                if not probe_site or probe_site == "demo":
                    probe_site = str(model.get("active_site_id") or site_id or "demo")
                ui = _run_probe(
                    "integrator_ui",
                    lambda: check_integrator_ui_api(base, login["token"], site_id=probe_site),
                )
                result["integrator_ui"] = ui
                result["errors"].extend(ui.get("errors", []))
                result["warnings"].extend(ui.get("warnings", []))
                bacnet = _run_probe("bacnet", lambda: check_bacnet_driver(base, login["token"]))
                result["bacnet"] = bacnet
                result["errors"].extend(bacnet.get("errors", []))
                result["warnings"].extend(bacnet.get("warnings", []))
                dash = _run_probe(
                    "building_dashboard",
                    lambda: check_building_dashboard_health(
                        base, login["token"], site_id=probe_site
                    ),
                )
                result["building_dashboard"] = dash
                result["errors"].extend(dash.get("errors", []))
                result["warnings"].extend(dash.get("warnings", []))
        else:
            result = check_entry(base, require_mcp=require_mcp, require_ollama=require_ollama)
        print(json.dumps(result, indent=2))
        return 0 if not result.get("errors") else 1
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
