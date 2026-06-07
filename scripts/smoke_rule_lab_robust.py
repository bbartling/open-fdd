#!/usr/bin/env python3
"""Robust Rule Lab smoke: constants-style Arrow rules, bindings, kit export, agent writes.

Validates that bench rules use module constants (not config.json), PyArrow batch runs,
AI agent can save/bind rules, and BRICK model links points to FDD.

  python3 scripts/smoke_rule_lab_robust.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
RULES_PY = REPO / "workspace" / "data" / "rules_py"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

BASE = os.environ.get("OPENFDD_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AUTH_ENV = REPO / "workspace" / "auth.env.local"
FAILURES = 0

BENCH_FILES = [
    "bench_oa-t_out_of_bounds.py",
    "bench_oa-t_flatline_1h.py",
    "bench_stat_zn-t_flatline_1h.py",
    "duct-t_flatline_1h.py",
    "duct-t_spread_1h.py",
    "bench_humidity_flatline_1h.py",
    "bench_humidity_out_of_bounds.py",
]

CUSTOM_RULE = '''"""Smoke custom OA-T high (Arrow constants)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
HIGH_LIMIT = 50.0


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(f"rows={table.num_rows} column={VALUE_COLUMN} max={pc.max(vals).as_py():.2f}")


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.greater(vals, HIGH_LIMIT)
'''


def ok(msg: str) -> None:
    print(f"  OK   {msg}")


def fail(msg: str) -> None:
    global FAILURES
    FAILURES += 1
    print(f"  FAIL {msg}", file=sys.stderr)


def _load_auth() -> tuple[str, str, str, str]:
    if AUTH_ENV.is_file():
        for line in AUTH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    int_u = os.environ.get("OFDD_INTEGRATOR_USER", "integrator")
    int_p = os.environ.get("OFDD_INTEGRATOR_PASSWORD", "changeme")
    ag_u = os.environ.get("OFDD_AGENT_USER", int_u)
    ag_p = os.environ.get("OFDD_AGENT_PASSWORD", int_p)
    return int_u, int_p, ag_u, ag_p


def _fetch(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    url = f"{BASE}{path}"
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
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def login(user: str, password: str) -> str:
    status, body = _fetch("POST", "/api/auth/login", body={"username": user, "password": password})
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        fail(f"login {user}: HTTP {status}")
        return ""
    return str(body["token"])


def check_bench_rules_arrow() -> None:
    import pyarrow as pa

    from open_fdd.arrow_runtime.backend import lint_arrow_rule, run_arrow_rule
    from open_fdd.arrow_runtime.rules import detect_rule_backend
    from openfdd_bridge.data_loader import load_frame_for_run

    print("\n==> Bench rules — constants + PyArrow execution")
    frame, origin = load_frame_for_run("demo")
    if frame is None or frame.empty:
        fail(f"no demo historian frame (origin={origin})")
        return
    table = pa.Table.from_pandas(frame.tail(200), preserve_index=False)

    for name in BENCH_FILES:
        path = RULES_PY / name
        if not path.is_file():
            fail(f"missing {name}")
            continue
        code = path.read_text(encoding="utf-8")
        if "VALUE_COLUMN" not in code:
            fail(f"{name} missing VALUE_COLUMN constant")
            continue
        if "apply_faults_arrow" not in code:
            fail(f"{name} missing apply_faults_arrow")
            continue
        backend = detect_rule_backend(code, {"mode": "rule"})
        if backend != "arrow":
            fail(f"{name} backend={backend} (expected arrow)")
            continue
        lint = lint_arrow_rule(code, strict_imports=True)
        if not lint.get("ok"):
            fail(f"{name} lint failed: {lint.get('issues')}")
            continue
        try:
            result = run_arrow_rule(code, table, {}, rule_id=name)
        except Exception as exc:
            fail(f"{name} run_arrow_rule: {exc}")
            continue
        if result.errors:
            fail(f"{name} arrow errors: {result.errors}")
            continue
        ok(f"{name} — arrow rows={result.row_count} flagged={result.true_count}")


def check_model_bindings() -> None:
    from openfdd_bridge.model_service import ModelService
    from openfdd_bridge.rule_store import RuleStore

    print("\n==> BRICK model ↔ rule bindings")
    model = ModelService().load()
    points = {str(p.get("id")): p for p in model.get("points", []) if isinstance(p, dict)}
    rules = RuleStore().list_rules()
    bound = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        pids = [str(x) for x in (bindings.get("point_ids") or []) if str(x).strip()]
        for pid in pids:
            pt = points.get(pid)
            if not pt:
                fail(f"rule {rule.get('id')} binds unknown point {pid}")
                continue
            col = str(pt.get("fdd_input") or pt.get("external_id") or "")
            if not col:
                fail(f"point {pid} missing fdd_input/external_id")
                continue
            bound += 1
    if bound < 4:
        fail(f"expected ≥4 point bindings, got {bound}")
    else:
        ok(f"{bound} point→rule binding(s) with historian column names")


def check_http_rule_workflow(token_int: str) -> None:
    print("\n==> HTTP Rule Lab — upload, quick test, export kit")
    status, body = _fetch("GET", "/api/rules/saved", token=token_int)
    if status != 200:
        fail(f"rules list HTTP {status}")
        return
    rules = (body.get("rules") or []) if isinstance(body, dict) else []
    oob = next((r for r in rules if r.get("id") == "bench-oa-t-oob"), None)
    if not oob:
        fail("bench-oa-t-oob not in saved rules — run setup_bench_afdd.py")
        return
    point_id = (oob.get("bindings") or {}).get("point_ids", [None])[0]
    status, src = _fetch("GET", "/api/rules/saved/bench-oa-t-oob/source", token=token_int)
    if status != 200 or "VALUE_COLUMN" not in str((src or {}).get("code") or ""):
        fail("bench-oa-t-oob source missing VALUE_COLUMN")
    else:
        ok("bench-oa-t-oob source view — constants style")

    status, test = _fetch(
        "POST",
        "/api/playground/test-rule",
        token=token_int,
        body={
            "code": str(src.get("code") or ""),
            "config": {},
            "site_id": "demo",
            "point_keys": [point_id],
            "lookback_hours": 3,
            "limit": 200,
        },
        timeout=90.0,
    )
    if status != 200 or not isinstance(test, dict):
        fail(f"quick test HTTP {status}")
    elif test.get("backend") != "arrow":
        fail(f"quick test backend={test.get('backend')} (expected arrow)")
    else:
        ok(f"quick test arrow — rows={test.get('rows')} flagged={test.get('flagged')}")

    status, _ = _fetch(
        "GET",
        "/api/rules/export-kit?site_id=demo&rule_id=bench-oa-t-oob&lookback_hours=3",
        token=token_int,
    )
    if status != 200:
        fail(f"export-kit HTTP {status}")
        return
    # Re-fetch as bytes via urllib for zip
    req = urllib.request.Request(
        f"{BASE}/api/rules/export-kit?site_id=demo&rule_id=bench-oa-t-oob&lookback_hours=3",
        headers={"Authorization": f"Bearer {token_int}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = set(zf.namelist())
    if "config.json" in names:
        fail("export kit still contains config.json")
    for required in ("rule.py", "sample.feather", "run_test.py", "requirements.txt"):
        if required not in names:
            fail(f"export kit missing {required}")
    rule_py = zf.read("rule.py").decode()
    if "VALUE_COLUMN" not in rule_py or "apply_faults_arrow" not in rule_py:
        fail("export kit rule.py invalid")
    else:
        ok(f"export kit — {len(names)} files, constants rule.py, no config.json")


def check_agent_rule_writes(token_agent: str) -> None:
    print("\n==> AI agent — rules.save, rules.bind, rules.run_batch")
    status, ctx = _fetch("GET", "/openfdd-agent/context", token=token_agent)
    if status != 200:
        fail(f"agent context HTTP {status}")
        return
    tool_names = {t.get("name") for t in (ctx.get("tools") or []) if isinstance(t, dict)}
    for needed in ("rules.save", "rules.bind", "rules.run_batch", "model.add_point", "model.graph"):
        if needed not in tool_names:
            fail(f"agent missing tool {needed}")
        else:
            ok(f"agent tool available — {needed}")

    status, saved = _fetch(
        "POST",
        "/openfdd-agent/tool",
        token=token_agent,
        body={
            "tool": "rules.save",
            "args": {
                "name": "Smoke custom high OA-T",
                "mode": "rule",
                "code": CUSTOM_RULE,
                "fault_code": "VAV-C",
                "config": {},
                "bindings": {"point_ids": ["5007-analog-input-1173"]},
            },
        },
    )
    if status != 200 or not isinstance(saved, dict) or saved.get("error"):
        fail(f"agent rules.save HTTP {status} {saved}")
        return
    rule = (saved.get("result") or {}).get("rule") or saved.get("rule") or {}
    rid = str(rule.get("id") or "")
    if not rid or "apply_faults_arrow" not in str(rule.get("code") or CUSTOM_RULE):
        fail("agent rules.save did not persist arrow rule")
    else:
        ok(f"agent rules.save — {rid}")

    status, batch = _fetch(
        "POST",
        "/openfdd-agent/tool",
        token=token_agent,
        body={"tool": "rules.run_batch", "args": {"limit": 5000, "lookback_hours": 1}},
        timeout=120.0,
    )
    if status != 200 or not isinstance(batch, dict) or batch.get("error"):
        fail(f"agent rules.run_batch HTTP {status} {batch}")
        return
    result = batch.get("result") or batch
    rules_run = int(result.get("rules_run") or 0)
    if rules_run < 1:
        fail("agent batch returned no runs")
    else:
        ok(f"agent rules.run_batch — {rules_run} rule run(s)")


def check_multi_rule_flex(token_int: str) -> None:
    print("\n==> Multi-rule flexibility")
    status, body = _fetch("GET", "/api/rules/saved", token=token_int)
    rules = (body.get("rules") or []) if isinstance(body, dict) else []
    arrow_rules = [r for r in rules if r.get("mode") == "rule" and str(r.get("id", "")).startswith("bench-")]
    if len(arrow_rules) < 5:
        fail(f"expected ≥5 bench rules, got {len(arrow_rules)}")
    else:
        ok(f"{len(arrow_rules)} bench Arrow rules loaded — add more via upload or agent rules.save")

    status, batch = _fetch(
        "POST",
        "/api/rules/batch",
        token=token_int,
        body={"limit": 5000, "lookback_hours": 1, "use_chunks": False},
        timeout=120.0,
    )
    if status != 200:
        fail(f"integrator batch HTTP {status}")
        return
    runs = batch.get("runs") or []
    arrow_runs = [r for r in runs if isinstance(r, dict) and r.get("backend") == "arrow"]
    if not arrow_runs:
        fail("batch had no arrow backend runs")
    else:
        flagged = sum(int(r.get("flagged") or 0) for r in arrow_runs)
        ok(f"batch arrow runs={len(arrow_runs)} flagged_rows={flagged}")


def main() -> int:
    print(f"\n==> Rule Lab robust smoke @ {BASE}")
    int_u, int_p, ag_u, ag_p = _load_auth()
    token_int = login(int_u, int_p)
    token_agent = login(ag_u, ag_p)
    if not token_int or not token_agent:
        print(f"\nSMOKE FAILED ({FAILURES} step(s))")
        return 1

    check_bench_rules_arrow()
    check_model_bindings()
    check_http_rule_workflow(token_int)
    check_agent_rule_writes(token_agent)
    check_multi_rule_flex(token_int)

    print("")
    if FAILURES:
        print(f"SMOKE FAILED ({FAILURES} step(s))", file=sys.stderr)
        return 1
    print("SMOKE OK — constants Arrow rules, BRICK bindings, kit export, agent writes, PyArrow batch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
