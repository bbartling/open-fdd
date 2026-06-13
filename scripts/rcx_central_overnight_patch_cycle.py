#!/usr/bin/env python3
"""RCx Central overnight patch-cycle validator (read-only Edge, gated live ACME).

Try-out:
  OPENFDD_LIVE_ACME=1 RCX_PATCH_CYCLES=2 RCX_CYCLE_SLEEP_MINUTES=0 \\
    python3 scripts/rcx_central_overnight_patch_cycle.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports" / "rcx_central_overnight_logs"
MASTER_REPORT = REPO / "reports" / "rcx_central_overnight_patch_cycle.md"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _http_json(url: str, *, timeout: float = 15.0) -> tuple[int, dict[str, Any] | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), ""
            except json.JSONDecodeError:
                return resp.status, None, body[:200]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return exc.code, None, detail
    except Exception as exc:
        return 0, None, str(exc)[:300]


def _git_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True)
        return out.strip()
    except Exception:
        return "unknown"


def _git_branch() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, text=True)
        return out.strip()
    except Exception:
        return "unknown"


def _run_pytest(targets: list[str]) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=line"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900, check=False)
    tail = (proc.stdout + proc.stderr)[-4000:]
    return proc.returncode == 0, tail


def _gh_pr_checks(pr: int) -> str:
    try:
        proc = subprocess.run(
            ["gh", "pr", "checks", str(pr)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return (proc.stdout or proc.stderr or "").strip() or "gh unavailable"
    except Exception as exc:
        return f"gh error: {exc}"


def _central_overview(api_url: str, site_id: str) -> dict[str, Any]:
    # CSV-only smoke — avoid blocking on unreachable Edge when credentials unset.
    code, data, err = _http_json(f"{api_url.rstrip('/')}/api/central/overview/{site_id}?live=false")
    if data is None:
        return {"ok": False, "http": code, "error": err}
    return {"ok": code == 200, "http": code, "data": data}


def _acme_edge_readonly(site_id: str) -> dict[str, Any]:
    """Query Edge via portfolio registry — no BACnet writes."""
    out: dict[str, Any] = {"site_id": site_id, "ok": False}
    try:
        sys.path.insert(0, str(REPO))
        from portfolio.central.edge_registry import resolve_site_config, resolve_token
        from portfolio.collector.edge_client import EdgeClient

        site = resolve_site_config(site_id)
        token = resolve_token(site)
        client = EdgeClient(site.base_url)
        out["edge_url"] = site.base_url
        health, _, err = _http_json(f"{site.base_url.rstrip('/')}/health")
        out["edge_health_http"] = health
        out["edge_health_error"] = err
        faults = client.get_faults_status(token=token)
        out["alert_count"] = faults.get("alert_count")
        out["families"] = len(faults.get("families") or [])
        try:
            mh = client.get_model_health(token=token)
            out["model_health"] = {
                "status": mh.get("status"),
                "score": mh.get("score"),
                "issues": len(mh.get("issues") or []),
            }
        except Exception as exc:
            out["model_health_error"] = str(exc)[:200]
        try:
            tree = client.get_model_tree(token=token)
            out["equipment_count"] = len(tree.get("equipment") or [])
            out["point_count"] = len(tree.get("points") or [])
        except Exception as exc:
            out["model_tree_error"] = str(exc)[:200]
        out["ok"] = health == 200
    except Exception as exc:
        out["error"] = str(exc)[:400]
    return out


def _write_cycle_log(cycle: int, body: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"cycle_{cycle:02d}.md"
    path.write_text(body, encoding="utf-8")
    return path


def run_cycle(cycle: int, *, pr_number: int) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    api_url = os.environ.get("RCX_CENTRAL_API_URL", "http://127.0.0.1:8060")
    dash_url = os.environ.get("RCX_CENTRAL_DASH_URL", "http://127.0.0.1:8050")
    site_id = os.environ.get("RCX_EDGE_SITE", "acme")
    live_acme = _env_bool("OPENFDD_LIVE_ACME")

    results: dict[str, Any] = {
        "cycle": cycle,
        "started_utc": started.isoformat(),
        "branch": _git_branch(),
        "sha": _git_sha(),
        "live_acme": live_acme,
    }

    api_code, _, api_err = _http_json(f"{api_url.rstrip('/')}/health")
    dash_code, _, dash_err = _http_json(dash_url)
    results["central_api"] = {"http": api_code, "error": api_err}
    results["central_dash"] = {"http": dash_code, "error": dash_err}

    results["gh_checks"] = _gh_pr_checks(pr_number)

    ok_tests, test_tail = _run_pytest(
        ["tests/portfolio", "tests/workspace_bridge/test_host_stats.py"]
    )
    results["tests_ok"] = ok_tests
    results["tests_tail"] = test_tail[-1200:]

    overview = _central_overview(api_url, site_id)
    results["overview"] = overview

    if live_acme:
        results["acme"] = _acme_edge_readonly(site_id)
    else:
        results["acme"] = {"skipped": True, "reason": "OPENFDD_LIVE_ACME not set"}

    ended = datetime.now(timezone.utc)
    results["ended_utc"] = ended.isoformat()
    results["duration_s"] = round((ended - started).total_seconds(), 1)

    acme_ok = True
    if live_acme:
        acme = results["acme"]
        acme_ok = bool(acme.get("ok")) and not acme.get("model_health_error") and not acme.get("model_tree_error")
    passed = (
        api_code == 200
        and dash_code == 200
        and ok_tests
        and overview.get("ok")
        and acme_ok
    )
    results["passed"] = passed

    md = [
        f"# RCx Central Patch Cycle {cycle:02d}",
        "",
        f"- Started: {results['started_utc']}",
        f"- Ended: {results['ended_utc']}",
        f"- Branch: `{results['branch']}` @ `{results['sha']}`",
        f"- Result: **{'PASS' if passed else 'FAIL'}**",
        "",
        "## GH Actions / PR",
        "```",
        results["gh_checks"],
        "```",
        "",
        "## RCx Central",
        f"- API `{api_url}`: HTTP {api_code}",
        f"- Dash `{dash_url}`: HTTP {dash_code}",
        f"- Overview `{site_id}`: {overview.get('ok')}",
        "",
        "## Tests",
        f"- portfolio + host_stats: {'PASS' if ok_tests else 'FAIL'}",
        "",
        "## ACME Edge (read-only)",
        "```json",
        json.dumps(results["acme"], indent=2)[:6000],
        "```",
        "",
        "## Next",
        "- Fix failing checks before merge.",
        "- Re-run with `RCX_CYCLE_SLEEP_MINUTES` spacing for overnight mode.",
        "",
    ]
    log_path = _write_cycle_log(cycle, "\n".join(md))
    results["log_path"] = str(log_path)
    return results


def _max_runtime_seconds() -> float:
    raw = os.environ.get("RCX_MAX_RUNTIME_HOURS", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw)) * 3600.0
    except ValueError:
        return 0.0


def main() -> int:
    max_cycles = min(_env_int("RCX_PATCH_CYCLES", 1), 10)
    sleep_min = _env_int("RCX_CYCLE_SLEEP_MINUTES", 0)
    cycle_start = max(1, _env_int("RCX_CYCLE_START", 1))
    pr_number = _env_int("RCX_PR_NUMBER", 298)
    max_runtime_s = _max_runtime_seconds()
    started_mono = time.monotonic()
    all_results: list[dict[str, Any]] = []

    print(
        f"RCx Central overnight patch-cycle — up to {max_cycles} cycle(s) "
        f"from #{cycle_start}"
        + (f", max {max_runtime_s / 3600:.1f}h" if max_runtime_s else "")
    )
    for i in range(max_cycles):
        if max_runtime_s and (time.monotonic() - started_mono) >= max_runtime_s:
            print("Max runtime reached — stopping.")
            break
        cycle = cycle_start + i
        print(f"\n=== Cycle {cycle} ({i + 1}/{max_cycles}) ===")
        res = run_cycle(cycle, pr_number=pr_number)
        all_results.append(res)
        print(f"Cycle {cycle}: {'PASS' if res['passed'] else 'FAIL'} → {res['log_path']}")
        if i + 1 < max_cycles and sleep_min > 0:
            if max_runtime_s and (time.monotonic() - started_mono + sleep_min * 60) >= max_runtime_s:
                print("Skipping sleep — would exceed max runtime.")
                break
            print(f"Sleeping {sleep_min} minutes…")
            time.sleep(sleep_min * 60)

    passed_n = sum(1 for r in all_results if r.get("passed"))
    summary = [
        "# RCx Central Overnight Patch-Cycle Summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Cycles: {len(all_results)} (passed {passed_n})",
        "",
        "| Cycle | Result | SHA | API | Dash | Tests |",
        "|---|---|---|---|---|---|",
    ]
    for r in all_results:
        summary.append(
            f"| {r['cycle']} | {'PASS' if r.get('passed') else 'FAIL'} | {r.get('sha')} | "
            f"{r['central_api'].get('http')} | {r['central_dash'].get('http')} | "
            f"{'ok' if r.get('tests_ok') else 'fail'} |"
        )
    MASTER_REPORT.parent.mkdir(parents=True, exist_ok=True)
    MASTER_REPORT.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"\nMaster report: {MASTER_REPORT}")
    return 0 if passed_n == len(all_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
