#!/usr/bin/env python3
"""Disposable authenticated ZAP Automation Framework runner (Wave U U5).

Soft-OPEN until a real disposable scan produces High=0 evidence.
Never logs or embeds JWT / Authorization header values in argv-style
output or verdict artifacts.

Modes:
  --selftest
      Validate af_plan.yaml hygiene + verdict schema; write BLOCKED verdict; exit 2.
  OPENFDD_ZAP_AF_EXECUTE=1 + ZAP_TARGET_ORIGIN + ZAP_AUTH_HEADER_VALUE
      If ZAP (docker image or zap.sh) is available: run AF passive (+ optional
      active when OPENFDD_ZAP_AF_ACTIVE=1), assert High=0, write verdict.
      If ZAP missing: hygiene selftest + BLOCKED verdict; exit 2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("ERROR: PyYAML required (pip/uv install pyyaml)") from e

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = Path(__file__).resolve().parent / "af_plan.yaml"
DEFAULT_VERDICT = ROOT / "reports" / "security" / "zap_af_verdict.json"
# Qualification default is digest-pinned (A07). Override only with another digest.
_PINNED_ZAP_DIGEST = (
    "ghcr.io/zaproxy/zaproxy@sha256:"
    "781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
)
DEFAULT_ZAP_IMAGE = os.environ.get("OPENFDD_ZAP_IMAGE", _PINNED_ZAP_DIGEST)

# Hardcoded JWT / Bearer material must never appear in the committed plan.
_HARDCODED_BEARER = re.compile(
    r"Bearer\s+(?!\$\{)[A-Za-z0-9\-_\.=]+", re.IGNORECASE
)
_JWT_BLOB = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_REDACT_BEARER = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip bearer token material from any string before logging/artifacts."""
    text = _REDACT_BEARER.sub(r"\1<redacted>", text)
    return _JWT_BLOB.sub("<redacted-jwt>", text)


def validate_af_plan(path: Path) -> list[str]:
    """Return human-readable hygiene errors (empty ⇒ OK)."""
    errors: list[str] = []
    if not path.is_file():
        return [f"missing plan: {path}"]
    raw = path.read_text(encoding="utf-8")
    if _HARDCODED_BEARER.search(raw):
        errors.append("plan contains hardcoded Bearer token (use env injection)")
    if _JWT_BLOB.search(raw):
        errors.append("plan contains JWT-like blob (never commit tokens)")
    if "${ZAP_AUTH_HEADER_VALUE}" not in raw:
        errors.append("plan must reference ${ZAP_AUTH_HEADER_VALUE} for Authorization")
    if "${ZAP_TARGET_ORIGIN}" not in raw:
        errors.append("plan must reference ${ZAP_TARGET_ORIGIN}")

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return errors + [f"invalid YAML: {e}"]

    if not isinstance(data, dict):
        return errors + ["plan root must be a mapping"]

    contexts = (data.get("env") or {}).get("contexts") or []
    if not isinstance(contexts, list) or not contexts:
        errors.append("env.contexts must be a nonempty list")
    else:
        for i, ctx in enumerate(contexts):
            if not isinstance(ctx, dict):
                errors.append(f"contexts[{i}] must be a mapping")
                continue
            urls = ctx.get("urls") or []
            if not isinstance(urls, list) or len(urls) == 0:
                errors.append(f"contexts[{i}].urls must be nonempty (site gate)")
            params = ((ctx.get("sessionManagement") or {}).get("parameters")) or {}
            auth = params.get("Authorization") if isinstance(params, dict) else None
            if auth != "${ZAP_AUTH_HEADER_VALUE}":
                errors.append(
                    f"contexts[{i}] Authorization must be exactly "
                    "'${ZAP_AUTH_HEADER_VALUE}'"
                )

    jobs = data.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must be a nonempty list")
    else:
        types = {j.get("type") for j in jobs if isinstance(j, dict)}
        for required in ("openapi", "spider", "passiveScan-wait", "report"):
            if required not in types:
                errors.append(f"jobs missing required type: {required}")
        for j in jobs:
            if isinstance(j, dict) and j.get("failOnError") is False:
                errors.append("failOnError=false must not swallow AF errors")

    return errors


def detect_zap() -> tuple[str | None, str]:
    """Return (mode, detail) where mode is 'zap.sh' | 'docker' | None."""
    zap_sh = shutil.which("zap.sh")
    if zap_sh:
        return "zap.sh", zap_sh
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "info"],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None, "docker present but daemon unavailable"
        # Prefer a local/pullable zaproxy image; do not pull here unless execute.
        return "docker", DEFAULT_ZAP_IMAGE
    return None, "neither zap.sh nor docker available"


def summarize_zap_json(data: dict[str, Any]) -> dict[str, Any]:
    sites = data.get("site") or data.get("sites") or []
    if isinstance(sites, dict):
        sites = [sites]
    if not isinstance(sites, list):
        sites = []
    alerts: list[dict[str, Any]] = []
    site_names: list[str] = []
    malformed_sites = 0
    for site in sites:
        if not isinstance(site, dict):
            malformed_sites += 1
            continue
        name = str(site.get("@name") or site.get("name") or "").strip()
        if not name and not (site.get("alerts") or []):
            malformed_sites += 1
        if name:
            site_names.append(name)
        for a in site.get("alerts") or []:
            if isinstance(a, dict):
                alerts.append(a)
    for a in data.get("alerts") or []:
        if isinstance(a, dict):
            alerts.append(a)

    by_risk = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0, "other": 0}
    high_names: list[str] = []
    medium_names: list[str] = []
    medium_plugins: list[str] = []
    url_blob_parts: list[str] = []
    for a in alerts:
        risk = str(a.get("riskdesc") or a.get("risk") or "").split(" ", 1)[0]
        code = str(a.get("riskcode") or "")
        if risk not in by_risk:
            risk = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}.get(
                code, "other"
            )
        by_risk[risk] = by_risk.get(risk, 0) + 1
        label = str(a.get("name") or a.get("alert") or "unknown")
        if risk == "High":
            high_names.append(label)
        if risk == "Medium":
            medium_names.append(label)
            plugin = str(a.get("pluginid") or a.get("alertRef") or "").strip()
            if plugin:
                medium_plugins.append(plugin)
        for key in ("url", "uri", "instance", "param"):
            val = a.get(key)
            if isinstance(val, str):
                url_blob_parts.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        url_blob_parts.append(str(item.get("uri") or item.get("url") or ""))
                    else:
                        url_blob_parts.append(str(item))
    for site in sites:
        if isinstance(site, dict):
            for key in ("@name", "name", "host"):
                if site.get(key):
                    url_blob_parts.append(str(site.get(key)))
            for u in site.get("urls") or []:
                url_blob_parts.append(str(u))
    url_blob = "\n".join(url_blob_parts).lower()
    # URL/text mention is informational only — never authenticated proof (Q-03).
    auth_me_url_mention = "/api/auth/me" in url_blob
    traffic = data.get("openfdd_auth_traffic")
    auth_me_hit = False
    auth_traffic: dict[str, Any] = {}
    if isinstance(traffic, dict):
        method = str(traffic.get("method") or "").strip().upper()
        path = str(traffic.get("path") or traffic.get("uri") or "").strip()
        try:
            status = int(traffic.get("status") or traffic.get("status_code") or 0)
        except (TypeError, ValueError):
            status = 0
        schema_ok = bool(traffic.get("identity_schema_ok") or traffic.get("schema_ok"))
        origin = str(traffic.get("origin") or "").strip().lower()
        auth_traffic = {
            "method": method,
            "path": path,
            "status": status,
            "identity_schema_ok": schema_ok,
            "origin": origin,
        }
        # Scanner-origin authenticated /api/auth/me with identity schema.
        auth_me_hit = (
            method == "GET"
            and path.rstrip("/").endswith("/api/auth/me")
            and status == 200
            and schema_ok
            and origin in ("scanner", "zap", "af")
        )
    return {
        "site_count": len(sites),
        "malformed_sites": malformed_sites,
        "site_names": site_names,
        "alert_count": len(alerts),
        "by_risk": by_risk,
        "high_alert_names": sorted(set(high_names)),
        "medium_alert_names": sorted(set(medium_names)),
        "medium_plugin_ids": sorted(set(medium_plugins)),
        "auth_me_url_mention": auth_me_url_mention,
        "auth_me_hit": auth_me_hit,
        "auth_traffic": auth_traffic,
    }


DISPOSITION_PATH = Path(__file__).resolve().parent / "medium_dispositions.json"
_REQUIRED_DISP_FIELDS = (
    "plugin_id",
    "alert_name",
    "component",
    "owner",
    "rationale",
    "expiry",
    "retest",
    "candidate_binding",
)


def load_medium_dispositions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load typed Medium dispositions (exact plugin scope; no blanket accept)."""
    p = path or DISPOSITION_PATH
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    items = raw.get("dispositions") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
    return out


def disposition_medium_alerts(
    *,
    medium_plugin_ids: list[str],
    medium_alert_names: list[str],
    dispositions: list[dict[str, Any]],
    today: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (covered_plugin_ids, errors).

    Every Medium plugin id must match exactly one disposition with required
    fields and a non-expired expiry (YYYY-MM-DD). Extra dispositions are OK.
    """
    from datetime import date

    day = today or date.today().isoformat()
    by_plugin: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for d in dispositions:
        missing = [k for k in _REQUIRED_DISP_FIELDS if not str(d.get(k) or "").strip()]
        if missing:
            errors.append(f"disposition missing fields {missing}")
            continue
        pid = str(d["plugin_id"]).strip()
        exp = str(d["expiry"]).strip()
        if exp < day:
            errors.append(f"disposition plugin {pid} expired {exp}")
            continue
        by_plugin[pid] = d
    covered: list[str] = []
    for pid in medium_plugin_ids:
        if pid in by_plugin:
            covered.append(pid)
        else:
            errors.append(f"undispositioned Medium plugin_id={pid}")
    # Name-only Mediums (no plugin id) cannot be dispositioned silently.
    if not medium_plugin_ids and medium_alert_names:
        errors.append(
            "Medium alerts lack plugin_id — cannot bind typed dispositions: "
            + ", ".join(medium_alert_names[:6])
        )
    return covered, errors


def verify_auth_me_response(
    *,
    status: int,
    body: bytes,
    content_type: str = "",
) -> dict[str, Any]:
    """Require HTTP 200 + JSON identity schema (role + subject).

    Report-string matching of /api/auth/me is never sufficient (Astra A06).
    """
    result: dict[str, Any] = {
        "ok": False,
        "status": int(status),
        "path": "/api/auth/me",
        "schema_ok": False,
    }
    if status != 200:
        result["error"] = "non_200"
        return result
    ctype = (content_type or "").lower()
    if ctype and "json" not in ctype and "text/plain" not in ctype:
        # Allow missing content-type from some stubs; reject explicit HTML.
        if "html" in ctype:
            result["error"] = "html_body"
            return result
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["error"] = "non_json"
        return result
    if not isinstance(data, dict) or not data:
        result["error"] = "empty_or_non_object"
        return result
    role = str(data.get("role") or "").strip()
    sub = str(data.get("sub") or data.get("username") or "").strip()
    if not role or not sub:
        result["error"] = "missing_role_or_subject"
        return result
    result["ok"] = True
    result["schema_ok"] = True
    result["role_present"] = True
    result["subject_present"] = True
    return result


def zap_image_is_digest_pinned(image: str) -> bool:
    return "@sha256:" in (image or "")


def fetch_auth_me_preflight(*, origin: str, auth_header: str) -> dict[str, Any]:
    """GET /api/auth/me with verified identity schema.

    When ``ZAP_DOCKER_NETWORK`` is set (disposable web+central), use
    ``docker run --network`` so Docker DNS names like ``web`` resolve.
    Never logs the Authorization value.
    """
    me_url = origin.rstrip("/") + "/api/auth/me"
    network = (os.environ.get("ZAP_DOCKER_NETWORK") or "").strip()
    if network:
        if not shutil.which("docker"):
            return {
                "ok": False,
                "path": "/api/auth/me",
                "error": "docker_missing_for_network_preflight",
                "schema_ok": False,
            }
        # Write body to a temp file inside a throwaway container mount is heavy;
        # capture stdout JSON via curl -w for status.
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    network,
                    "curlimages/curl:8.5.0",
                    "-sS",
                    "-D",
                    "-",
                    "-o",
                    "-",
                    "-H",
                    f"Authorization: {auth_header}",
                    "-H",
                    "Accept: application/json",
                    me_url,
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return {
                "ok": False,
                "path": "/api/auth/me",
                "error": type(e).__name__,
                "schema_ok": False,
                "via": "docker_network",
            }
        raw = proc.stdout or b""
        # Split headers/body on first blank line.
        sep = raw.find(b"\r\n\r\n")
        if sep < 0:
            sep = raw.find(b"\n\n")
        if sep < 0:
            return {
                "ok": False,
                "path": "/api/auth/me",
                "error": "docker_curl_malformed",
                "schema_ok": False,
                "via": "docker_network",
                "rc": proc.returncode,
            }
        header_blob = raw[:sep].decode("utf-8", errors="replace")
        body = raw[sep:].lstrip(b"\r\n")
        status = 0
        ctype = ""
        for line in header_blob.splitlines():
            if line.upper().startswith("HTTP/"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status = int(parts[1])
            elif line.lower().startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        result = verify_auth_me_response(
            status=status, body=body, content_type=ctype
        )
        result["via"] = "docker_network"
        if proc.returncode != 0 and not result.get("ok"):
            result["error"] = result.get("error") or f"docker_curl_rc_{proc.returncode}"
        return result

    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            me_url,
            method="GET",
            headers={"Authorization": auth_header, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            body = resp.read(1_048_576)
            ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
            result = verify_auth_me_response(
                status=status, body=body, content_type=ctype
            )
            result["via"] = "urllib"
            return result
    except Exception as e:  # noqa: BLE001 — map to structured preflight failure
        import urllib.error

        if isinstance(e, urllib.error.HTTPError):
            try:
                body = e.read(1_048_576)
            except Exception:  # noqa: BLE001
                body = b""
            result = verify_auth_me_response(
                status=int(e.code),
                body=body,
                content_type=e.headers.get("Content-Type", "") if e.headers else "",
            )
            if result.get("error") == "non_200":
                result["error"] = "http_error"
            result["via"] = "urllib"
            return result
        return {
            "ok": False,
            "path": "/api/auth/me",
            "error": type(e).__name__,
            "schema_ok": False,
            "via": "urllib",
        }


def validate_report_sites(data: dict[str, Any], target_origin: str) -> list[str]:
    """Require nonempty site objects belonging to the configured target."""
    sites = data.get("site") or data.get("sites") or []
    if isinstance(sites, dict):
        sites = [sites]
    if not isinstance(sites, list) or not sites:
        return ["report has no site objects"]

    target = urlsplit(target_origin.rstrip("/"))
    target_key = (target.scheme.lower(), target.netloc.lower())
    errors: list[str] = []
    for index, site in enumerate(sites):
        if not isinstance(site, dict) or not site:
            errors.append(f"site[{index}] must be a nonempty object")
            continue
        raw_name = str(site.get("@name") or site.get("name") or "").strip()
        parsed = urlsplit(raw_name)
        if not raw_name or not parsed.scheme or not parsed.netloc:
            errors.append(f"site[{index}] missing valid target name")
        elif (parsed.scheme.lower(), parsed.netloc.lower()) != target_key:
            errors.append(
                f"site[{index}] target does not match configured target origin"
            )
    return errors


def verdict_schema_ok(verdict: dict[str, Any]) -> list[str]:
    """Validate verdict object shape; also reject embedded secrets."""
    errors: list[str] = []
    required = (
        "suite",
        "status",
        "mode",
        "plan_hygiene_ok",
        "high_alerts",
        "medium_alerts",
        "zap_available",
        "active_scan",
        "notes",
    )
    for k in required:
        if k not in verdict:
            errors.append(f"verdict missing key: {k}")
    if verdict.get("status") not in ("PASS", "FAIL", "BLOCKED", "ERROR"):
        errors.append(f"invalid status: {verdict.get('status')!r}")
    blob = json.dumps(verdict)
    if _JWT_BLOB.search(blob) or _HARDCODED_BEARER.search(blob):
        errors.append("verdict must not embed JWT / Bearer tokens")
    return errors


def write_verdict(path: Path, verdict: dict[str, Any]) -> None:
    errs = verdict_schema_ok(verdict)
    if errs:
        raise SystemExit("ERROR: refusing to write invalid verdict: " + "; ".join(errs))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")


def build_verdict(**kwargs: Any) -> dict[str, Any]:
    base = {
        "suite": "zap_af_authenticated_v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": str(PLAN_PATH.relative_to(ROOT)),
        "artifact_policy": "no_jwt_in_verdict_or_ci_logs",
    }
    base.update(kwargs)
    # Defense in depth: redact any accidental secret fields.
    return json.loads(redact(json.dumps(base)))


def stage_openapi_spec(*, work_dir: Path, origin: str) -> tuple[bool, str]:
    """Fetch a real OpenAPI document into work_dir/openapi.json.

    SPA/nginx often returns HTML for ``/openapi.json``. Prefer the central
    service on the disposable Docker network, then an explicit override URL.
    Returns (ok, detail) without logging secrets.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / "openapi.json"
    # Honor a pre-staged fixture (unit tests / offline CI helpers).
    if dest.is_file() and dest.stat().st_size >= 32:
        try:
            parsed = json.loads(dest.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and (parsed.get("openapi") or parsed.get("swagger")):
                parsed["servers"] = [{"url": origin.rstrip("/")}]
                dest.write_text(json.dumps(parsed), encoding="utf-8")
                return True, f"reused staged openapi.json ({dest.stat().st_size} bytes)"
        except Exception:  # noqa: BLE001
            pass
    override = os.environ.get("OPENFDD_ZAP_OPENAPI_URL", "").strip()
    network = os.environ.get("ZAP_DOCKER_NETWORK", "").strip()
    candidates: list[str] = []
    if override:
        candidates.append(override)
    if network:
        candidates.append("http://central:8080/openapi.json")
    # Last resort: origin path (may be HTML through nginx — validated below).
    candidates.append(origin.rstrip("/") + "/openapi.json")

    body: bytes | None = None
    used = ""
    for url in candidates:
        try:
            if network and ("central:" in url or "web:" in url):
                proc = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        network,
                        "curlimages/curl:8.5.0",
                        "-fsS",
                        "--max-time",
                        "20",
                        url,
                    ],
                    capture_output=True,
                    timeout=60,
                )
                if proc.returncode != 0:
                    continue
                body = proc.stdout or b""
            else:
                # Host-side fetch; disable env proxies/redirects for hygiene.
                import urllib.request

                req = urllib.request.Request(url, method="GET")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req, timeout=20) as resp:  # noqa: S310 — controlled URL list
                    body = resp.read(2_000_000)
            used = url
            break
        except Exception:  # noqa: BLE001 — try next candidate
            body = None
            continue

    if not body:
        return False, "could not fetch OpenAPI from central/override/origin"

    text = body.lstrip()
    if text[:1] not in (b"{", b"[") and not text.startswith(b"openapi:") and not text.startswith(
        b"swagger:"
    ):
        return False, f"OpenAPI body is not JSON/YAML (source={used.split('/')[2] if '://' in used else 'local'})"

    # Prefer JSON parse when it looks like JSON.
    if text[:1] == b"{":
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return False, f"OpenAPI JSON parse failed: {type(exc).__name__}"
        if not isinstance(parsed, dict) or not (
            parsed.get("openapi") or parsed.get("swagger")
        ):
            return False, "OpenAPI JSON missing openapi/swagger field"
        # ZAP OpenAPI AF requires a resolvable server URL; central's shipped
        # spec often omits servers[]. Bind the disposable scan origin.
        parsed["servers"] = [{"url": origin.rstrip("/")}]
        dest.write_text(json.dumps(parsed), encoding="utf-8")
    else:
        dest.write_bytes(body)
        # YAML specs without servers still break ZAP — require JSON path above
        # for disposable qualification.

    if dest.stat().st_size < 32:
        return False, "OpenAPI staged file too small"
    return True, f"staged openapi.json ({dest.stat().st_size} bytes)"


def materialize_plan(
    *,
    origin: str,
    report_dir: str,
    active: bool,
    dest: Path,
) -> None:
    """Write AF plan with origin/reportDir expanded; auth stays env-referenced."""
    raw = PLAN_PATH.read_text(encoding="utf-8")
    # Expand only non-secret placeholders for ZAP hosts that skip env expansion.
    rendered = raw.replace("${ZAP_TARGET_ORIGIN}", origin.rstrip("/"))
    rendered = rendered.replace("${ZAP_REPORT_DIR}", report_dir)
    data = yaml.safe_load(rendered)
    # Force file-based OpenAPI so SPA HTML cannot poison the AF openapi job.
    for j in data.get("jobs") or []:
        if isinstance(j, dict) and j.get("type") == "openapi":
            params = j.setdefault("parameters", {})
            params.pop("apiUrl", None)
            params["apiFile"] = "/zap/wrk/openapi.json" if report_dir.startswith("/zap/") else str(
                Path(report_dir) / "openapi.json"
            )
            params["targetUrl"] = origin.rstrip("/")
            params.setdefault("context", "openfdd-disposable")
    if active:
        jobs = list(data.get("jobs") or [])
        # Insert activeScan before the report job.
        active_job = {
            "type": "activeScan",
            "parameters": {
                "context": "openfdd-disposable",
                "policy": "Default Policy",
                "maxRuleDurationInMins": 5,
                "maxScanDurationInMins": 30,
            },
        }
        out_jobs: list[Any] = []
        inserted = False
        for j in jobs:
            if isinstance(j, dict) and j.get("type") == "report" and not inserted:
                out_jobs.append(active_job)
                inserted = True
            out_jobs.append(j)
        if not inserted:
            out_jobs.append(active_job)
        data["jobs"] = out_jobs
    # Ensure Authorization still env-only after round-trip.
    for ctx in (data.get("env") or {}).get("contexts") or []:
        if not isinstance(ctx, dict):
            continue
        sm = ctx.setdefault("sessionManagement", {})
        params = sm.setdefault("parameters", {})
        params["Authorization"] = "${ZAP_AUTH_HEADER_VALUE}"
    dest.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    # Re-check only secret hygiene on rendered text (origin is expanded).
    text = dest.read_text(encoding="utf-8")
    if _HARDCODED_BEARER.search(text) or _JWT_BLOB.search(text):
        raise SystemExit("ERROR: rendered plan leaked auth material")
    if "${ZAP_AUTH_HEADER_VALUE}" not in text:
        raise SystemExit("ERROR: rendered plan lost auth env injection")


def _run_zap_docker(
    *,
    image: str,
    work_dir: Path,
    auth_header: str,
    origin: str,
) -> int:
    network = os.environ.get("ZAP_DOCKER_NETWORK", "").strip()
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{work_dir}:/zap/wrk:rw",
        "-e",
        "ZAP_AUTH_HEADER_VALUE",  # value from caller env — not argv
        "-e",
        f"ZAP_TARGET_ORIGIN={origin}",
        "-e",
        "ZAP_REPORT_DIR=/zap/wrk",
        "-u",
        "0:0",
    ]
    # Host-reachable disposable targets vs shared docker network (mutually exclusive).
    if "127.0.0.1" in origin or "localhost" in origin:
        cmd.append("--network=host")
    elif network:
        cmd.extend(["--network", network])
    cmd.extend([image, "zap.sh", "-cmd", "-autorun", "/zap/wrk/af_plan.yaml"])
    env = os.environ.copy()
    env["ZAP_AUTH_HEADER_VALUE"] = auth_header
    # Do not print cmd with secrets; auth is env-pass only.
    print(
        "Running ZAP AF via docker "
        f"(image={image}, network={network or 'default/host'}, active check deferred to plan)",
        flush=True,
    )
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    (work_dir / "zap_af.stdout.log").write_text(redact(proc.stdout or ""), encoding="utf-8")
    (work_dir / "zap_af.stderr.log").write_text(redact(proc.stderr or ""), encoding="utf-8")
    return int(proc.returncode)


def _run_zap_sh(*, zap_sh: str, work_dir: Path, auth_header: str, origin: str) -> int:
    env = os.environ.copy()
    env["ZAP_AUTH_HEADER_VALUE"] = auth_header
    env["ZAP_TARGET_ORIGIN"] = origin
    env["ZAP_REPORT_DIR"] = str(work_dir)
    plan = work_dir / "af_plan.yaml"
    print(f"Running ZAP AF via zap.sh ({zap_sh})", flush=True)
    proc = subprocess.run(
        [zap_sh, "-cmd", "-autorun", str(plan)],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(work_dir),
    )
    (work_dir / "zap_af.stdout.log").write_text(redact(proc.stdout or ""), encoding="utf-8")
    (work_dir / "zap_af.stderr.log").write_text(redact(proc.stderr or ""), encoding="utf-8")
    return int(proc.returncode)


def run_selftest(verdict_path: Path) -> int:
    """Prove plan hygiene + verdict schema; never claim PASS without a scan."""
    hygiene = validate_af_plan(PLAN_PATH)
    mode, detail = detect_zap()
    plan_ok = not hygiene
    sample = build_verdict(
        status="BLOCKED",
        mode="selftest",
        plan_hygiene_ok=plan_ok,
        plan_hygiene_errors=hygiene,
        high_alerts=0,
        medium_alerts=0,
        site_count=0,
        zap_available=mode is not None,
        zap_detection=detail if mode is None else mode,
        active_scan=False,
        execute_requested=False,
        notes=(
            "Selftest only: plan hygiene + verdict schema. "
            "Not a scan PASS. Soft-OPEN until OPENFDD_ZAP_AF_EXECUTE=1 "
            "against a disposable target with ZAP produces High=0."
        ),
    )
    schema_errs = verdict_schema_ok(sample)
    if hygiene or schema_errs:
        sample["status"] = "ERROR"
        sample["notes"] = redact(
            "Selftest failed: "
            + "; ".join(hygiene + schema_errs)
        )
        write_verdict(verdict_path, sample)
        print(json.dumps(sample, indent=2))
        print("ERROR: selftest hygiene/schema failed", file=sys.stderr)
        return 1
    write_verdict(verdict_path, sample)
    print(json.dumps(sample, indent=2))
    print(
        f"BLOCKED: selftest OK (hygiene+schema); Soft-OPEN → {verdict_path}",
        file=sys.stderr,
    )
    return 2


def run_execute(verdict_path: Path) -> int:
    os.environ.setdefault("ZAP_AF_RUN_STARTED_EPOCH", str(time.time()))
    hygiene = validate_af_plan(PLAN_PATH)
    if hygiene:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=False,
            plan_hygiene_errors=hygiene,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            active_scan=False,
            execute_requested=True,
            notes="af_plan.yaml hygiene failed: " + "; ".join(hygiene),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    origin = (os.environ.get("ZAP_TARGET_ORIGIN") or "").strip()
    auth = (os.environ.get("ZAP_AUTH_HEADER_VALUE") or "").strip()
    if not origin or not auth:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            active_scan=False,
            execute_requested=True,
            notes=(
                "BLOCKED: set ZAP_TARGET_ORIGIN and ZAP_AUTH_HEADER_VALUE in env "
                "(never argv). Disposable target only."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    # Never echo auth. Confirm it looks like a header value without printing it.
    if not auth.lower().startswith("bearer "):
        print(
            "WARN: ZAP_AUTH_HEADER_VALUE does not start with 'Bearer ' "
            "(continuing; value not logged)",
            file=sys.stderr,
        )

    # A06: prove authenticated /api/auth/me with status + JSON identity schema.
    # Report URL text alone is never authenticated proof.
    # Disposable stacks use Docker DNS names (web/central); when
    # ZAP_DOCKER_NETWORK is set, fetch via that network (host urllib cannot).
    auth_me_preflight = fetch_auth_me_preflight(origin=origin, auth_header=auth)
    if not auth_me_preflight.get("ok"):
        v = build_verdict(
            status="FAIL",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            active_scan=False,
            execute_requested=True,
            target_origin_configured=True,
            auth_header_configured=True,
            auth_me_hit=False,
            auth_me_preflight=auth_me_preflight,
            notes=(
                "FAIL: authenticated GET /api/auth/me preflight missing "
                "200 + JSON identity (role+subject); report-string auth is not proof"
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    mode, detail = detect_zap()
    active = os.environ.get("OPENFDD_ZAP_AF_ACTIVE", "").strip() in ("1", "true", "yes")
    require_digest = os.environ.get("OPENFDD_ZAP_REQUIRE_DIGEST", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if require_digest and mode == "docker" and not zap_image_is_digest_pinned(detail):
        v = build_verdict(
            status="FAIL",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=detail,
            active_scan=active,
            execute_requested=True,
            target_origin_configured=True,
            auth_header_configured=True,
            auth_me_preflight=auth_me_preflight,
            notes=(
                "FAIL: OPENFDD_ZAP_REQUIRE_DIGEST=1 but scanner image is not "
                "@sha256: digest-pinned"
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    if mode is None:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            zap_detection=detail,
            active_scan=active,
            execute_requested=True,
            target_origin_configured=True,
            auth_header_configured=True,
            notes=(
                "BLOCKED: ZAP not installed/available. Plan hygiene OK. "
                "Not a fake High=0 PASS. Install zap.sh or docker+zaproxy image."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    work_root = Path(
        os.environ.get("ZAP_AF_WORK_DIR")
        or tempfile.mkdtemp(prefix="openfdd_zap_af_")
    )
    work_root.mkdir(parents=True, exist_ok=True)
    staged_ok, staged_detail = stage_openapi_spec(work_dir=work_root, origin=origin)
    if not staged_ok:
        v = build_verdict(
            status="FAIL",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            active_scan=active,
            execute_requested=True,
            target_origin_configured=True,
            auth_header_configured=True,
            auth_me_preflight=auth_me_preflight,
            notes=f"FAIL: OpenAPI staging failed ({staged_detail})",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1
    # Docker mounts work_root at /zap/wrk
    report_dir_in_plan = "/zap/wrk" if mode == "docker" else str(work_root)
    plan_dest = work_root / "af_plan.yaml"
    materialize_plan(
        origin=origin,
        report_dir=report_dir_in_plan,
        active=active,
        dest=plan_dest,
    )

    scan_started_ns = time.time_ns()
    if mode == "docker":
        # Ensure image exists (pull if missing) — low-RAM hosts may already have it.
        try:
            inspect = subprocess.run(
                ["docker", "image", "inspect", detail],
                capture_output=True,
                timeout=60,
            )
            if inspect.returncode != 0:
                print(f"Pulling ZAP image {detail} …", flush=True)
                subprocess.run(["docker", "pull", detail], check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            v = build_verdict(
                status="BLOCKED",
                mode="execute",
                plan_hygiene_ok=True,
                high_alerts=0,
                medium_alerts=0,
                site_count=0,
                zap_available=False,
                zap_detection=f"docker image unavailable: {redact(str(e))}",
                active_scan=active,
                execute_requested=True,
                notes="BLOCKED: could not pull/inspect ZAP image",
            )
            write_verdict(verdict_path, v)
            print(json.dumps(v, indent=2))
            return 2
        rc = _run_zap_docker(
            image=detail, work_dir=work_root, auth_header=auth, origin=origin
        )
    else:
        rc = _run_zap_sh(
            zap_sh=detail, work_dir=work_root, auth_header=auth, origin=origin
        )

    report_path = work_root / "zap-af-report.json"
    # ZAP traditional-json may append .json or write variants.
    if not report_path.is_file():
        candidates = sorted(work_root.glob("zap-af-report*.json"))
        report_path = candidates[0] if candidates else report_path

    if rc != 0:
        v = build_verdict(
            status="FAIL",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes=f"FAIL: ZAP scanner exited nonzero (rc={rc})",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    if not report_path.is_file() or report_path.stat().st_size == 0:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            work_dir=str(work_root),
            notes=(
                "BLOCKED: ZAP finished without usable JSON report "
                f"(rc={rc}). Not treating as High=0 PASS."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    if report_path.stat().st_mtime_ns < scan_started_ns:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: ZAP report predates this scan run; stale evidence rejected",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            active_scan=active,
            execute_requested=True,
            notes=f"ERROR: malformed ZAP JSON: {e}",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    if not isinstance(data, dict):
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: ZAP report root must be object",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    site_errors = validate_report_sites(data, origin)
    if site_errors:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: invalid ZAP report sites: " + "; ".join(site_errors),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    summary = summarize_zap_json(data)
    high = int(summary["by_risk"].get("High", 0))
    med = int(summary["by_risk"].get("Medium", 0))
    sites = int(summary["site_count"])
    malformed_sites = summary.get("malformed_sites", 0)

    # Reject reused/stale reports or wrong-target crawls.
    report_mtime = report_path.stat().st_mtime
    run_started = float(os.environ.get("ZAP_AF_RUN_STARTED_EPOCH", "0") or "0")
    if run_started <= 0:
        # Infer: if report mtime is far older than process start, treat as stale.
        run_started = time.time() - 2.0
    stale = report_mtime + 1.0 < run_started
    site_names = summary.get("site_names") or []
    wrong_target = bool(site_names) and not any(
        origin.rstrip("/") in str(name).rstrip("/")
        or str(name).rstrip("/") in origin.rstrip("/")
        for name in site_names
    )

    # Archive report under reports/security without secrets (ZAP JSON usually
    # has URLs, not Authorization headers — still redact defensively).
    archive = verdict_path.parent / "zap_af_report.json"
    archive.write_text(redact(report_path.read_text(encoding="utf-8")), encoding="utf-8")

    medium_observed = med
    medium_covered: list[str] = []
    status = "PASS"
    notes = ""
    exit_code = 0

    if rc != 0:
        status = "FAIL"
        notes = f"FAIL: ZAP scanner exit rc={rc} (report present is not a PASS)"
        exit_code = 1
    elif stale:
        status = "FAIL"
        notes = "FAIL: ZAP report mtime predates this run (stale/reused artifact)"
        exit_code = 1
    elif wrong_target:
        status = "FAIL"
        notes = f"FAIL: report site names {site_names!r} do not match target {origin}"
        exit_code = 1
    elif malformed_sites or sites == 0:
        status = "FAIL" if malformed_sites else "BLOCKED"
        notes = (
            "FAIL: malformed empty site objects — no crawl/auth coverage"
            if malformed_sites
            else "BLOCKED: empty site[] — no crawl/auth coverage evidence"
        )
        exit_code = 1 if malformed_sites else 2
    elif high > 0:
        status = "FAIL"
        notes = f"FAIL: High={high} ({', '.join(summary['high_alert_names'][:8])})"
        exit_code = 1
    elif med > 0:
        dispositions = load_medium_dispositions()
        medium_covered, disp_errors = disposition_medium_alerts(
            medium_plugin_ids=list(summary.get("medium_plugin_ids") or []),
            medium_alert_names=list(summary.get("medium_alert_names") or []),
            dispositions=dispositions,
        )
        if disp_errors:
            status = "FAIL"
            notes = (
                f"FAIL: Medium={med} without complete typed dispositions "
                f"({'; '.join(disp_errors[:6])})"
            )
            exit_code = 1
        else:
            # Exact plugin dispositions applied — not a blanket Medium accept.
            med = 0

    if exit_code == 0 and not auth_me_preflight.get("ok"):
        status = "FAIL"
        notes = "FAIL: authenticated /api/auth/me preflight schema failed"
        exit_code = 1
    elif exit_code == 0 and active and not bool(summary.get("auth_me_hit")):
        # Preflight proves credentials work; authenticated AF still requires
        # scanner-origin structured /api/auth/me traffic (not URL text) (Q-03).
        status = "FAIL"
        mention = bool(summary.get("auth_me_url_mention"))
        notes = (
            "FAIL: active AF missing scanner-origin structured /api/auth/me traffic "
            f"(url_mention={mention}; preflight alone is not authenticated coverage)"
        )
        exit_code = 1
    elif exit_code == 0:
        status = "PASS"
        disp_note = (
            f" medium_dispositioned={medium_covered}"
            if medium_covered
            else ""
        )
        notes = (
            f"PASS: disposable AF High=0 Medium_undispositioned=0 "
            f"Medium_observed={medium_observed} site_count={sites} "
            f"auth_me_preflight=true auth_me_in_report={bool(summary.get('auth_me_hit'))} "
            f"auth_me_url_mention={bool(summary.get('auth_me_url_mention'))} "
            f"active_scan={active} zap_rc={rc}{disp_note}"
        )

    scanner_auth = bool(summary.get("auth_me_hit"))
    v = build_verdict(
        status=status,
        mode="execute",
        plan_hygiene_ok=True,
        high_alerts=high,
        medium_alerts=medium_observed,
        medium_undispositioned=med,
        medium_dispositions_applied=medium_covered,
        site_count=sites,
        alert_count=summary["alert_count"],
        high_alert_names=summary["high_alert_names"],
        zap_available=True,
        zap_detection=mode,
        zap_exit_code=rc,
        active_scan=active,
        execute_requested=True,
        target_origin_configured=True,
        auth_header_configured=True,
        auth_me_hit=bool(auth_me_preflight.get("ok")),
        auth_me_preflight=auth_me_preflight,
        auth_me_in_zap_report=scanner_auth,
        auth_me_url_mention=bool(summary.get("auth_me_url_mention")),
        auth_traffic=summary.get("auth_traffic") or {},
        auth_proof=(
            "preflight_schema+scanner_auth_traffic"
            if active and scanner_auth
            else "preflight_status_identity_schema"
        ),
        zap_image=detail if mode == "docker" else None,
        zap_image_digest_pinned=(
            zap_image_is_digest_pinned(detail) if mode == "docker" else None
        ),
        report_archive=str(archive.relative_to(ROOT)) if archive.is_relative_to(ROOT) else str(archive),
        work_dir=str(work_root),
        notes=notes,
    )
    write_verdict(verdict_path, v)
    print(json.dumps(v, indent=2))
    print(f"{status}: → {verdict_path}", file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--selftest",
        action="store_true",
        help="plan hygiene + verdict schema; exit BLOCKED (2), never PASS",
    )
    p.add_argument(
        "--out",
        default=str(DEFAULT_VERDICT),
        help=f"verdict JSON path (default: {DEFAULT_VERDICT})",
    )
    args = p.parse_args(argv)
    out = Path(args.out)

    if args.selftest:
        return run_selftest(out)

    execute = os.environ.get("OPENFDD_ZAP_AF_EXECUTE", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if not execute:
        print(
            "BLOCKED: set OPENFDD_ZAP_AF_EXECUTE=1 for a real disposable scan, "
            "or pass --selftest for hygiene-only BLOCKED evidence.",
            file=sys.stderr,
        )
        v = build_verdict(
            status="BLOCKED",
            mode="idle",
            plan_hygiene_ok=not validate_af_plan(PLAN_PATH),
            plan_hygiene_errors=validate_af_plan(PLAN_PATH),
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=detect_zap()[0] is not None,
            active_scan=False,
            execute_requested=False,
            notes=(
                "OPENFDD_ZAP_AF_EXECUTE not set — refusing to invent a scan PASS. "
                "Use --selftest or EXECUTE=1 with ZAP_TARGET_ORIGIN + "
                "ZAP_AUTH_HEADER_VALUE."
            ),
        )
        write_verdict(out, v)
        print(json.dumps(v, indent=2))
        return 2

    return run_execute(out)


if __name__ == "__main__":
    sys.exit(main())
