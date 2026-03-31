#!/usr/bin/env python3
"""
AI / data-model payload regression test for OpenClaw bench use.

Purpose:
- fail fast on auth drift
- exercise malformed payloads and partial payloads
- verify engineering metadata + Standard 223 / s223 topology JSON survives API round-trips
- verify export/import parity at the API level on a fresh site

This is intentionally tester-focused and stays in the OpenClaw lane. It does not patch product code.

Checks performed:
1. Auth preflight (GET /sites)
2. Malformed import payload should fail (fixture: points is not an array)
3. Partial payload missing site should fail clearly
4. Fresh-site retargeted import should materialize HVAC/weather equipment + points
5. Engineering metadata PATCH on imported equipment should persist
6. GET /data-model/export should include engineering metadata/topology for the edited equipment
7. Retargeted re-import of the edited site into a second fresh site should preserve engineering metadata

Typical usage:
    python openclaw/bench/e2e/5_ai_data_model_payload_test.py \
      --api-url http://192.168.204.16:8000 \
      --save-report

PowerShell:
    python .\\openclaw\\bench\\e2e\\5_ai_data_model_payload_test.py `
      --api-url http://192.168.204.16:8000 `
      --save-report
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
FIXTURES_DIR = SCRIPT_DIR.parent / "fixtures"


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and os.environ.get(k) is None:
            os.environ[k] = v.strip('"').strip("'")


def _load_stack_env() -> None:
    extra = os.environ.get("OPENCLAW_STACK_ENV", "").strip()
    candidates: list[Path] = []
    if extra:
        candidates.append(Path(extra))
    candidates.extend(
        [
            REPO_ROOT / "stack" / ".env",
            Path.cwd() / ".env",
            SCRIPT_DIR / ".env",
            Path.home() / ".openclaw" / "workspace" / "open-fdd" / "stack" / ".env",
        ]
    )
    for c in candidates:
        _load_env_file(str(c))


_load_stack_env()
API_KEY = os.environ.get("OFDD_API_KEY", "").strip()


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _request(api_url: str, method: str, path: str, json_body: Any | None = None) -> tuple[int, Any, str]:
    try:
        import httpx
    except ImportError:
        print("pip install httpx", file=sys.stderr)
        sys.exit(1)
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    url = f"{api_url.rstrip('/')}{path}"
    try:
        r = httpx.request(method, url, json=json_body, headers=headers or None, timeout=60, trust_env=False)
        try:
            body = r.json() if r.content else {}
        except Exception:
            body = {"raw": r.text[:1000]}
        err = ""
        if r.status_code >= 400:
            if isinstance(body, dict):
                if isinstance(body.get("error"), dict) and body["error"].get("message"):
                    err = str(body["error"]["message"])
                elif body.get("detail") is not None:
                    err = str(body["detail"])
            if not err:
                err = (r.text or "").strip()[:1000]
        return r.status_code, body, err
    except Exception as exc:
        return 0, {}, str(exc)


def _auth_preflight(api_url: str) -> tuple[bool, str]:
    code, _, err = _request(api_url, "GET", "/sites")
    if code == 200:
        return True, "Auth preflight OK"
    if code == 401 and not API_KEY:
        return False, "Auth preflight FAIL — backend requires OFDD_API_KEY but none was loaded"
    if code in (401, 403):
        return False, f"Auth preflight FAIL — backend rejected OFDD_API_KEY ({code})"
    if code == 0:
        return False, f"Auth preflight FAIL — transport error: {err}"
    return False, f"Auth preflight FAIL — GET /sites -> {code} {err}".strip()


def _expect_failure(api_url: str, payload: Any, label: str) -> dict[str, Any]:
    code, body, err = _request(api_url, "PUT", "/data-model/import", payload)
    ok = code >= 400
    return {
        "label": label,
        "utc": _utc(),
        "status_code": code,
        "ok": ok,
        "error": err,
        "body": body,
    }


def _expect_partial_noop(api_url: str, payload: Any, label: str) -> dict[str, Any]:
    code, body, err = _request(api_url, "PUT", "/data-model/import", payload)
    warnings = body.get("warnings") if isinstance(body, dict) else None
    ok = (
        code == 200
        and isinstance(body, dict)
        and int(body.get("created", 0) or 0) == 0
        and int(body.get("updated", 0) or 0) == 0
        and isinstance(warnings, list)
        and len(warnings) >= 1
    )
    return {
        "label": label,
        "utc": _utc(),
        "status_code": code,
        "ok": ok,
        "error": err,
        "body": body,
    }


def _create_site(api_url: str, name_prefix: str) -> dict[str, Any]:
    body = {"name": f"{name_prefix}-{uuid4().hex[:8]}", "description": "OpenClaw AI payload regression"}
    code, resp, err = _request(api_url, "POST", "/sites", body)
    if code != 200:
        raise RuntimeError(f"Create site failed: {code} {err}")
    return resp


def _get_equipment(api_url: str, site_id: str) -> list[dict[str, Any]]:
    code, body, err = _request(api_url, "GET", f"/equipment?site_id={site_id}")
    if code != 200:
        raise RuntimeError(f"Get equipment failed: {code} {err}")
    return list(body)


def _get_points(api_url: str, site_id: str) -> list[dict[str, Any]]:
    code, body, err = _request(api_url, "GET", f"/points?site_id={site_id}")
    if code != 200:
        raise RuntimeError(f"Get points failed: {code} {err}")
    return list(body)


def _patch_equipment_metadata(api_url: str, equipment_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    code, body, err = _request(api_url, "PATCH", f"/equipment/{equipment_id}", {"metadata": metadata})
    if code != 200:
        raise RuntimeError(f"Patch equipment failed: {code} {err}")
    return body


def _get_export(api_url: str) -> list[dict[str, Any]]:
    code, body, err = _request(api_url, "GET", "/data-model/export")
    if code != 200:
        raise RuntimeError(f"Export failed: {code} {err}")
    return list(body)


def _retarget_points_payload(payload: dict[str, Any], site_id: str, site_name: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    for p in out.get("points", []):
        p["site_id"] = site_id
        p["site_name"] = site_name
    for e in out.get("equipment", []):
        e["site_id"] = site_id
    return out


def _retarget_export_rows(rows: list[dict[str, Any]], from_site_id: str, to_site_id: str, to_site_name: str) -> dict[str, Any]:
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("site_id") != from_site_id:
            continue
        r = copy.deepcopy(row)
        r["point_id"] = None
        r["equipment_id"] = None
        r["site_id"] = to_site_id
        r["site_name"] = to_site_name
        out_rows.append(r)
    return {"points": out_rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    ap.add_argument("--save-report", nargs="?", const="", default=None)
    args = ap.parse_args()

    report: dict[str, Any] = {
        "utc_started": _utc(),
        "api_url": args.api_url.rstrip("/"),
        "fixtures": {},
        "results": {},
    }

    ok, msg = _auth_preflight(args.api_url)
    report["auth_preflight"] = {"ok": ok, "message": msg, "api_key_loaded": bool(API_KEY)}
    if not ok:
        print(msg, file=sys.stderr)
        if args.save_report is not None:
            out = Path(args.save_report) if args.save_report else (SCRIPT_DIR / f"ai_payload_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    malformed_path = FIXTURES_DIR / "demo_site_llm_payload_malformed.json"
    missing_site_path = FIXTURES_DIR / "demo_site_llm_payload_missing_site.json"
    full_payload_path = FIXTURES_DIR / "demo_site_llm_payload.json"
    report["fixtures"] = {
        "malformed": {"path": str(malformed_path), "sha256": _sha256_path(malformed_path)},
        "missing_site": {"path": str(missing_site_path), "sha256": _sha256_path(missing_site_path)},
        "full_payload": {"path": str(full_payload_path), "sha256": _sha256_path(full_payload_path)},
    }

    malformed_payload = json.loads(malformed_path.read_text(encoding="utf-8-sig"))
    missing_site_payload = json.loads(missing_site_path.read_text(encoding="utf-8-sig"))
    full_payload = json.loads(full_payload_path.read_text(encoding="utf-8-sig"))

    report["results"]["malformed_payload"] = _expect_failure(args.api_url, malformed_payload, "points-not-array")
    report["results"]["partial_missing_site"] = _expect_partial_noop(args.api_url, missing_site_payload, "missing-site")

    site1 = _create_site(args.api_url, "OpenClawAI")
    report["results"]["site1"] = {"utc": _utc(), "site": site1}
    retargeted = _retarget_points_payload(full_payload, site1["id"], site1["name"])
    code, body, err = _request(args.api_url, "PUT", "/data-model/import", retargeted)
    if code != 200:
        raise RuntimeError(f"Fresh-site import failed: {code} {err}")
    eq1 = _get_equipment(args.api_url, site1["id"])
    pts1 = _get_points(args.api_url, site1["id"])
    report["results"]["fresh_site_import"] = {
        "utc": _utc(),
        "import_response": body,
        "equipment_count": len(eq1),
        "equipment_names": sorted(e["name"] for e in eq1),
        "point_count": len(pts1),
        "point_sample": sorted(p.get("external_id") for p in pts1[:12]),
    }

    ahu = next((e for e in eq1 if e.get("name") == "AHU-1"), None)
    if not ahu:
        raise RuntimeError("AHU-1 not found after import")
    engineering = {
        "controls": {"control_vendor": "OpenClawTest", "communication_protocols": "BACnet/IP"},
        "mechanical": {"design_cfm": "2500", "equipment_tag": "AHU-1"},
        "topology": {
            "connection_points": [
                {"id": "ahu-supply-out", "name": "AHU Supply Outlet"},
                {"id": "vav-inlet", "name": "VAV Inlet"},
            ],
            "connections": [
                {"from": "ahu-supply-out", "to": "vav-inlet", "medium": "duct-1"}
            ],
            "mediums": [
                {"id": "duct-1", "type": "Duct"}
            ],
        },
        "extensions": {"s223": {"source": "openclaw-regression"}},
    }
    patched = _patch_equipment_metadata(args.api_url, ahu["id"], {**(ahu.get("metadata") or {}), "engineering": engineering})
    report["results"]["engineering_patch"] = {
        "utc": _utc(),
        "equipment_id": ahu["id"],
        "patched_metadata": patched.get("metadata"),
    }

    export_rows = _get_export(args.api_url)
    site1_rows = [r for r in export_rows if r.get("site_id") == site1["id"]]
    matching = [r for r in site1_rows if r.get("equipment_name") == "AHU-1" and r.get("engineering")]
    report["results"]["export_parity"] = {
        "utc": _utc(),
        "site_row_count": len(site1_rows),
        "engineering_rows_found": len(matching),
        "sample_engineering": matching[0].get("engineering") if matching else None,
    }

    site2 = _create_site(args.api_url, "OpenClawAIReplay")
    report["results"]["site2"] = {"utc": _utc(), "site": site2}
    replay_payload = _retarget_export_rows(export_rows, site1["id"], site2["id"], site2["name"])
    code, body, err = _request(args.api_url, "PUT", "/data-model/import", replay_payload)
    if code != 200:
        raise RuntimeError(f"Replay import failed: {code} {err}")
    eq2 = _get_equipment(args.api_url, site2["id"])
    ahu2 = next((e for e in eq2 if e.get("name") == "AHU-1"), None)
    report["results"]["reimport_parity"] = {
        "utc": _utc(),
        "import_response": body,
        "equipment_count": len(eq2),
        "engineering_preserved": bool(ahu2 and isinstance((ahu2.get("metadata") or {}).get("engineering"), dict)),
        "engineering_metadata": (ahu2.get("metadata") or {}).get("engineering") if ahu2 else None,
    }

    report["summary"] = {
        "malformed_payload_failed": report["results"]["malformed_payload"]["ok"],
        "partial_payload_warned_without_materializing": report["results"]["partial_missing_site"]["ok"],
        "fresh_import_equipment_count": report["results"]["fresh_site_import"]["equipment_count"],
        "fresh_import_point_count": report["results"]["fresh_site_import"]["point_count"],
        "engineering_rows_found_in_export": report["results"]["export_parity"]["engineering_rows_found"],
        "engineering_reimport_preserved": report["results"]["reimport_parity"]["engineering_preserved"],
    }

    out_text = json.dumps(report, indent=2)
    print(out_text)
    if args.save_report is not None:
        out = Path(args.save_report) if args.save_report else (SCRIPT_DIR / f"ai_payload_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
        out.write_text(out_text, encoding="utf-8")
        print(f"\nSaved report: {out}")
    failed = not all(
        [
            report["results"]["malformed_payload"]["ok"],
            report["results"]["partial_missing_site"]["ok"],
            report["results"]["fresh_site_import"]["equipment_count"] >= 3,
            report["results"]["fresh_site_import"]["point_count"] >= 20,
            report["results"]["export_parity"]["engineering_rows_found"] >= 1,
            report["results"]["reimport_parity"]["engineering_preserved"],
        ]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
