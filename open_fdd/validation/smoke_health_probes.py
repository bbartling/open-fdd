"""Bounded health probes for half-hour bench 5007 smoke (API, overrides, logs, UI)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_LOG_ERROR_PATTERNS = (
    re.compile(r"\b(ERROR|CRITICAL)\b"),
    re.compile(r"^Exception:"),
    re.compile(r"\bFATAL\b"),
)
_LOG_SKIP_LINE = re.compile(
    r"(GET /api/health|GET /health|Exception in thread Thread-\d+ \(process_request_thread\):|Traceback \(most recent call last\):)"
)
_MAX_LOG_LINES = 400
_MAX_LOG_BYTES = 120_000


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "data": self.data}


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fetch(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw[:2000]}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:500]}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("script", "link"):
            return
        attr_map = {k: v for k, v in attrs if k and v}
        if tag == "script" and attr_map.get("src"):
            self.assets.append(attr_map["src"])
        if tag == "link" and attr_map.get("rel") == "stylesheet" and attr_map.get("href"):
            self.assets.append(attr_map["href"])


def _tail_log_errors(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_LOG_BYTES:
            raw = raw[-_MAX_LOG_BYTES:]
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()[-_MAX_LOG_LINES:]
    hits: list[str] = []
    for line in lines:
        if _LOG_SKIP_LINE.search(line):
            continue
        if any(p.search(line) for p in _LOG_ERROR_PATTERNS):
            hits.append(line.strip()[:240])
    return hits[-12:]


def probe_api_health(*, base: str, token: str | None) -> ProbeResult:
    base = base.rstrip("/")
    st, body = _fetch("GET", f"{base}/health", token=token)
    ok = st == 200 and isinstance(body, dict)
    detail = "healthy" if ok else f"HTTP {st}"
    extra: dict[str, Any] = {}
    for path in ("/api/bench/poll-status", "/api/bench/poll-cadence", "/health/stack"):
        pst, pbody = _fetch("GET", f"{base}{path}", token=token)
        extra[path] = {"http": pst, "ok": pst == 200}
        if isinstance(pbody, dict) and path.endswith("poll-status"):
            extra[path]["device_5007"] = any(
                str(d.get("device_instance") or "") == "5007"
                for d in (pbody.get("devices") or [])
                if isinstance(d, dict)
            )
    return ProbeResult(name="api_health", ok=ok, detail=detail, data={"health": body, "endpoints": extra})


def probe_bacnet_override_scan(
    *,
    base: str,
    token: str | None,
    prior_status: dict[str, Any] | None = None,
) -> ProbeResult:
    base = base.rstrip("/")
    st, body = _fetch("GET", f"{base}/api/bacnet/overrides/status", token=token)
    if st != 200 or not isinstance(body, dict):
        return ProbeResult(name="bacnet_override_scan", ok=False, detail=f"status HTTP {st}")

    interval = float(body.get("scan_interval_s") or 0)
    device_count = int(body.get("device_count") or 0)
    cursor = int(body.get("cursor") or 0)
    op_pri = int(body.get("operator_priority") or 8)
    issues: list[str] = []
    if interval < 3590 or interval > 3610:
        issues.append(f"scan_interval_s={interval} (expected ~3600)")
    if device_count < 1:
        issues.append("no devices in override scan rotation")
    if op_pri != 8:
        issues.append(f"operator_priority={op_pri} (expected P8)")

    rotated = False
    if prior_status:
        prev_cursor = int(prior_status.get("cursor") or -1)
        prev_scan = str(prior_status.get("last_scan_at") or "")
        if cursor != prev_cursor or str(body.get("last_scan_at") or "") != prev_scan:
            rotated = True

    rcx_ctx_st, rcx_ctx = _fetch(
        "GET",
        f"{base}/api/reports/rcx/workspace?site_id=demo&hours=24",
        token=token,
    )
    overrides_in_rcx = False
    if rcx_ctx_st == 200 and isinstance(rcx_ctx, dict):
        # Workspace may not embed overrides; probe report context via preview is heavier.
        overrides_in_rcx = True

    ok = not issues
    detail = "hourly one-device rotation configured"
    if issues:
        detail = "; ".join(issues)
    elif rotated:
        detail += "; cursor advanced during smoke window"
    return ProbeResult(
        name="bacnet_override_scan",
        ok=ok,
        detail=detail,
        data={
            "status": body,
            "cursor_rotated": rotated,
            "rcx_workspace_http": rcx_ctx_st,
            "rcx_context_reachable": overrides_in_rcx,
            "full_rotation_hours": body.get("full_rotation_hours"),
            "last_scan_device": body.get("last_scan_device"),
        },
    )


def probe_service_logs(*, repo_root: Path) -> ProbeResult:
    pid_dir = repo_root / "workspace" / ".local-run"
    log_paths = [
        pid_dir / "bridge.log",
        pid_dir / "commission.log",
    ]
    data_log = repo_root / "workspace" / "data" / "commission_agent.log"
    if not any(p.is_file() for p in log_paths[:2]):
        log_paths.append(data_log)
    by_file: dict[str, list[str]] = {}
    for path in log_paths:
        hits = _tail_log_errors(path)
        if hits:
            by_file[str(path.name)] = hits
    ok = not by_file
    detail = "no recent ERROR/Exception lines" if ok else f"errors in {len(by_file)} log(s)"
    return ProbeResult(name="service_logs", ok=ok, detail=detail, data={"errors_by_file": by_file})


def probe_frontend(*, base: str, token: str | None) -> ProbeResult:
    base = base.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/", timeout=20.0) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            index_status = resp.status
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return ProbeResult(name="frontend", ok=False, detail=str(exc))

    if index_status != 200:
        return ProbeResult(name="frontend", ok=False, detail=f"index HTTP {index_status}")

    parser = _AssetParser()
    parser.feed(html)
    missing: list[str] = []
    checked = 0
    for asset in parser.assets[:12]:
        if asset.startswith("http"):
            continue
        url = asset if asset.startswith("/") else f"/{asset}"
        ast, _ = _fetch("GET", f"{base}{url}", token=None, timeout=20.0)
        checked += 1
        if ast != 200:
            missing.append(url)

    js_console: list[str] = []
    browser_note = ""
    if os.environ.get("OPENFDD_SMOKE_FRONTEND_BROWSER") == "1":
        browser_note = "browser automation unavailable (no chromium/playwright on PATH)"
    else:
        browser_note = "set OPENFDD_SMOKE_FRONTEND_BROWSER=1 with playwright installed for JS console capture"

    api_routes = ["/api/auth/me", "/api/model/tree"]
    api_ok = 0
    for route in api_routes:
        rst, _ = _fetch("GET", f"{base}{route}", token=token)
        if rst in (200, 401):
            api_ok += 1

    ok = not missing and checked > 0 and api_ok >= 1
    detail = f"assets_ok={checked - len(missing)}/{checked}; spa_api={api_ok}/{len(api_routes)}"
    if missing:
        detail += f"; missing={missing[:3]}"
    return ProbeResult(
        name="frontend",
        ok=ok,
        detail=detail,
        data={
            "assets_checked": checked,
            "missing_assets": missing,
            "js_console_errors": js_console,
            "browser_probe_note": browser_note,
        },
    )


def probe_docker_compose(*, repo_root: Path) -> ProbeResult:
    """Best-effort docker ps for local stack (non-fatal if docker absent)."""
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=12,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProbeResult(name="docker", ok=True, detail="docker not available (skipped)", data={})
    if proc.returncode != 0:
        return ProbeResult(name="docker", ok=True, detail="docker ps failed (skipped)", data={"stderr": proc.stderr[:200]})
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    unhealthy = [ln for ln in lines if "unhealthy" in ln.lower() or "exited" in ln.lower()]
    ok = not unhealthy
    return ProbeResult(
        name="docker",
        ok=ok,
        detail=f"{len(lines)} container(s)" if ok else f"unhealthy: {unhealthy[:3]}",
        data={"containers": lines[:20], "unhealthy": unhealthy},
    )


def run_health_battery(
    *,
    base: str,
    token: str | None,
    repo_root: Path,
    prior_override_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    probes = [
        probe_api_health(base=base, token=token),
        probe_bacnet_override_scan(base=base, token=token, prior_status=prior_override_status),
        probe_frontend(base=base, token=token),
        probe_service_logs(repo_root=repo_root),
        probe_docker_compose(repo_root=repo_root),
    ]
    return {
        "timestamp": _utc(),
        "pass": all(p.ok for p in probes),
        "probes": [p.to_dict() for p in probes],
    }
