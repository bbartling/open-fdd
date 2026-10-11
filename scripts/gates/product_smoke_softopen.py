#!/usr/bin/env python3
"""Soft-OPEN 371 T0c/T3d — product smoke Soft-OPEN gate (API + revision).

Hard FAIL Soft-OPEN when any of:
  - sidebar/health revision ≠ OPENFDD_EXPECTED_REVISION
  - analytics/FDD/RCx body is nginx 502 HTML / Central analytics unavailable
  - avg(Utf8View) / avg(String) / planning error text
  - empty motor weekly (runtime) or BAS-vs-web with mapped roles but no rows
    (missing map roles → BLOCKED, never silent PASS)

MEGA/ZAP alone cannot Soft-OPEN. This gate is the product smoke half; real
Selenium/Playwright dual-site browser remains mandatory (T3e/T7).

Env:
  OPENFDD_API_BASE (default http://127.0.0.1:8080)
  OPENFDD_EXPECTED_REVISION (required)
  OPENFDD_SOFTOPEN_SITES (default BUILDING_100,ACME)
  OPENFDD_ADMIN_PASSWORD (+ OPENFDD_ADMIN_USER)
  OPENFDD_AGENT_PASSWORD (preferred when set; user agent)
  ARTIFACT_DIR / OPENFDD_PRODUCT_SMOKE_ART
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HTML_MARKERS = (
    "<html",
    "502 Bad Gateway",
    "503 Service",
    "504 Gateway",
    "Central analytics unavailable",
    "nginx/",
)

PLANNING_MARKERS = (
    "Utf8View",
    "avg(Utf8View",
    "avg(String",
    "failed to match",
    "No function matches",
    "SchemaError",
    "planning error",
    "Error during planning",
    "SanityCheckPlan",
)

# Soft-OPEN product surfaces (subset of Overview / RCx / Inspect).
SOFTOPEN_POSTS: list[tuple[str, str]] = [
    ("analytics_runtime", "/api/analytics/runtime"),
    ("analytics_mechanical_cooling", "/api/analytics/mechanical-cooling"),
    ("analytics_bas_vs_web_oat", "/api/analytics/bas-vs-web-oat"),
    ("analytics_ahu_health", "/api/analytics/ahu-health"),
    ("analytics_rcx_ahu", "/api/analytics/rcx/ahu"),
    ("analytics_inspect", "/api/analytics/inspect"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 120.0,
) -> tuple[int, object, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        code = e.code
    except TimeoutError as e:
        return 0, {"error": f"timeout after {timeout}s: {e}"}, f"timeout after {timeout}s"
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}, str(e)
    try:
        return code, json.loads(raw) if raw else {}, raw
    except json.JSONDecodeError:
        return code, raw, raw


def login(base: str) -> tuple[str, str]:
    agent_pw = os.environ.get("OPENFDD_AGENT_PASSWORD", "").strip()
    admin_pw = os.environ.get("OPENFDD_ADMIN_PASSWORD", "").strip()
    if agent_pw:
        user = os.environ.get("OPENFDD_AGENT_USER", "agent")
        password = agent_pw
    elif admin_pw:
        user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
        password = admin_pw
    else:
        raise SystemExit("FAIL: set OPENFDD_AGENT_PASSWORD or OPENFDD_ADMIN_PASSWORD")
    code, out, _ = http_json(
        "POST",
        f"{base}/api/auth/login",
        body={"username": user, "password": password},
        timeout=30.0,
    )
    if code != 200 or not isinstance(out, dict):
        raise SystemExit(f"FAIL: login HTTP {code}")
    tok = out.get("token") or out.get("access_token")
    if not tok:
        raise SystemExit("FAIL: login missing token")
    return str(tok), user


def is_html_or_gateway(raw: str, code: int) -> str | None:
    if code in (502, 503, 504):
        return f"HTTP {code}"
    low = raw.lower()
    for m in HTML_MARKERS:
        if m.lower() in low:
            return m
    return None


def has_planning_error(raw: str) -> bool:
    low = raw.lower()
    return any(m.lower() in low for m in PLANNING_MARKERS)


def envelope_rows(body: object) -> int:
    if not isinstance(body, dict):
        return 0
    a = body.get("analytics") if isinstance(body.get("analytics"), dict) else body
    if not isinstance(a, dict):
        return 0
    for key in ("rows", "equipment", "points", "series"):
        v = a.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


def mapped_roles(mapping: object) -> set[str]:
    roles: set[str] = set()
    if not isinstance(mapping, dict):
        return roles
    eq = mapping.get("equipment")
    if not isinstance(eq, list):
        return roles
    for item in eq:
        if not isinstance(item, dict):
            continue
        cols = item.get("columns") or item.get("roles") or item.get("mapped_roles")
        if isinstance(cols, dict):
            roles.update(str(k) for k in cols.keys())
        elif isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict) and c.get("role"):
                    roles.add(str(c["role"]))
                elif isinstance(c, str):
                    roles.add(c)
    return roles


def revision_matches(actual: str | None, expected: str) -> bool:
    if not actual:
        return False
    exp = expected.strip()
    act = actual.strip()
    if act == exp:
        return True
    # Allow shortsha prefix match: 3.5.71+4002de0 vs 3.5.71+4002de0e628c
    if "+" in exp and "+" in act:
        sem_e, sha_e = exp.split("+", 1)
        sem_a, sha_a = act.split("+", 1)
        if sem_e == sem_a and (sha_a.startswith(sha_e) or sha_e.startswith(sha_a)):
            return True
    return False


def probe_site(
    *,
    base: str,
    token: str,
    site: str,
    art: Path,
    lookback_days: int,
    hard_timeout: float,
    start_override: str | None,
) -> dict:
    site_art = art / re.sub(r"[^A-Za-z0-9_.-]+", "_", site)
    site_art.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    fails = 0
    blocked = 0

    start = (start_override or "").strip()
    if not start:
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    window: dict = {
        "building_id": site,
        "max_points": 4000,
        "start": start,
        "refresh": True,
    }

    path = f"/api/csv/import/package/mapping?building_id={urllib.parse.quote(site)}"
    code, mapping, raw = http_json("GET", f"{base}{path}", token=token, timeout=60.0)
    (site_art / "mapping.json").write_text(raw if isinstance(raw, str) else json.dumps(mapping, indent=2))
    html = is_html_or_gateway(raw, code)
    if html or code >= 500 or has_planning_error(raw):
        rows.append(
            {
                "name": "package_mapping",
                "status": "FAIL",
                "http_code": code,
                "reason": html or "mapping transport/planning FAIL",
            }
        )
        fails += 1
        roles: set[str] = set()
    elif code != 200:
        rows.append({"name": "package_mapping", "status": "FAIL", "http_code": code})
        fails += 1
        roles = set()
    else:
        roles = mapped_roles(mapping)
        rows.append({"name": "package_mapping", "status": "PASS", "http_code": code, "roles_n": len(roles)})

    for name, api_path in SOFTOPEN_POSTS:
        code, out, raw = http_json(
            "POST",
            f"{base}{api_path}",
            token=token,
            body=dict(window),
            timeout=hard_timeout,
        )
        (site_art / f"{name}.json").write_text(
            raw if isinstance(out, str) else json.dumps(out, indent=2)[:2_000_000]
        )
        entry: dict = {"name": name, "http_code": code, "path": api_path}
        html = is_html_or_gateway(raw, code)
        if html:
            entry["status"] = "FAIL"
            entry["reason"] = f"gateway/html: {html}"
            fails += 1
        elif has_planning_error(raw):
            entry["status"] = "FAIL"
            entry["reason"] = "planning_error"
            fails += 1
        elif code >= 500:
            entry["status"] = "FAIL"
            entry["reason"] = f"HTTP {code}"
            fails += 1
        elif code != 200:
            entry["status"] = "FAIL"
            entry["reason"] = f"HTTP {code}"
            fails += 1
        else:
            nrows = envelope_rows(out)
            entry["rows"] = nrows
            if name == "analytics_runtime" and nrows == 0:
                fanish = {r for r in roles if "fan" in r.lower() or "pump" in r.lower()}
                if not fanish and "fan_status" not in roles and "fan-status" not in roles:
                    entry["status"] = "BLOCKED"
                    entry["reason"] = "package-map missing fan/pump status roles for motor weekly"
                    blocked += 1
                else:
                    entry["status"] = "FAIL"
                    entry["reason"] = "empty motor/runtime with mapped fan/pump roles"
                    fails += 1
            elif name == "analytics_bas_vs_web_oat" and nrows == 0:
                has_bas = "oa_t" in roles or "outside-air-temp" in roles
                has_web = "web_oa_t" in roles or "web-outside-air-temp" in roles
                if not (has_bas and has_web):
                    entry["status"] = "BLOCKED"
                    entry["reason"] = "package-map missing distinct BAS oa_t + web_oa_t"
                    blocked += 1
                else:
                    entry["status"] = "FAIL"
                    entry["reason"] = "empty BAS-vs-web with both OAT roles mapped"
                    fails += 1
            else:
                entry["status"] = "PASS"
        rows.append(entry)

    verdict = "PASS"
    if fails:
        verdict = "FAIL"
    elif blocked:
        verdict = "BLOCKED"
    summary = {
        "site": site,
        "verdict": verdict,
        "fails": fails,
        "blocked": blocked,
        "start": start,
        "rows": rows,
    }
    (site_art / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument(
        "--expected-revision",
        default=os.environ.get("OPENFDD_EXPECTED_REVISION", ""),
    )
    ap.add_argument(
        "--sites",
        default=os.environ.get("OPENFDD_SOFTOPEN_SITES", "BUILDING_100,ACME"),
        help="Comma-separated building_ids (default BUILDING_100,ACME)",
    )
    ap.add_argument(
        "--artifact-dir",
        default=os.environ.get("OPENFDD_PRODUCT_SMOKE_ART")
        or os.environ.get("ARTIFACT_DIR")
        or "",
    )
    ap.add_argument("--lookback-days", type=int, default=int(os.environ.get("OPENFDD_GATE_LOOKBACK_DAYS", "30")))
    ap.add_argument(
        "--hard-timeout-secs",
        type=float,
        default=float(os.environ.get("OPENFDD_GATE_HARD_TIMEOUT_SECS", "120")),
    )
    ap.add_argument(
        "--start",
        default=os.environ.get("OPENFDD_GATE_START", ""),
        help="Fixed ISO start (BUILDING_100 historian window)",
    )
    args = ap.parse_args()
    expected = (args.expected_revision or "").strip()
    if not expected:
        print("FAIL: OPENFDD_EXPECTED_REVISION / --expected-revision required", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    art = Path(args.artifact_dir) if args.artifact_dir else ROOT / "reports" / f"product_smoke_{utc_now().replace(':', '')}"
    art.mkdir(parents=True, exist_ok=True)

    token, user = login(base)
    code, health, raw = http_json("GET", f"{base}/api/health", token=token, timeout=30.0)
    (art / "health.json").write_text(raw if isinstance(health, str) else json.dumps(health, indent=2))
    if code != 200 or not isinstance(health, dict):
        print(json.dumps({"verdict": "FAIL", "reason": f"health HTTP {code}"}))
        return 2
    version = health.get("version") if isinstance(health.get("version"), str) else None
    if not revision_matches(version, expected):
        payload = {
            "verdict": "VERSION_MISMATCH",
            "expected": expected,
            "actual": version,
            "artifact_dir": str(art),
        }
        (art / "SUMMARY.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(payload))
        return 4

    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    if not sites:
        print("FAIL: no sites", file=sys.stderr)
        return 2

    site_summaries = []
    for site in sites:
        site_summaries.append(
            probe_site(
                base=base,
                token=token,
                site=site,
                art=art,
                lookback_days=args.lookback_days,
                hard_timeout=args.hard_timeout_secs,
                start_override=args.start or None,
            )
        )

    fails = sum(1 for s in site_summaries if s["verdict"] == "FAIL")
    blocked = sum(1 for s in site_summaries if s["verdict"] == "BLOCKED")
    if fails:
        verdict = "FAIL"
        rc = 2
    elif blocked:
        verdict = "BLOCKED"
        rc = 3
    else:
        verdict = "PASS"
        rc = 0

    payload = {
        "verdict": verdict,
        "expected_revision": expected,
        "actual_revision": version,
        "login_user": user,
        "sites": site_summaries,
        "artifact_dir": str(art),
        "generated_at": utc_now(),
        "note": "API product smoke only — Selenium/Playwright dual-site still required for Soft-OPEN",
    }
    (art / "SUMMARY.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"verdict": verdict, "fails": fails, "blocked": blocked, "artifact_dir": str(art)}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
