#!/usr/bin/env python3
"""AI-agent-style Open-FDD commissioning bootstrap (API-only, no git push)."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from openfdd_test_lib import (
    CANONICAL_OA_SQL,
    Check,
    OpenFddClient,
    RunResult,
    bench_config,
    bench_root,
    build_agent_commissioning_payload,
    classify_product_bug,
    historian_snapshot,
    json_api_poll_body,
    log,
    resolve_password,
    utc_now,
    wait_for_historian_growth,
    write_sql_artifact,
)


def run_bootstrap(out_dir: Path, skip_import: bool = False) -> RunResult:
    root = bench_root()
    cfg = bench_config(root)
    result = RunResult(artifact_dir=str(out_dir), started_at=utc_now(), meta={"phase": "agent_bootstrap", "cfg": cfg})
    out_dir.mkdir(parents=True, exist_ok=True)

    user, pw = resolve_password(root, "integrator")
    client = OpenFddClient.login(cfg["bridge"], user, pw)

    st, health = client.get("/api/health")
    client.save_json(out_dir / "health.json", st, health)
    if st == 200 and isinstance(health, dict) and health.get("ok"):
        ver = health.get("version") or health.get("tag") or "?"
        result.add(Check("health", "PASS", f"bridge ok version={ver}"))
    else:
        result.add(Check("health", "FAIL", f"/api/health status={st}", product_bug=False))

    st, host_stats = client.get("/api/host/stats")
    client.save_json(out_dir / "host_stats.json", st, host_stats)
    if st == 200 and isinstance(host_stats, dict) and host_stats.get("ok", True):
        cpu = (host_stats.get("host") or {}).get("cpu_percent")
        result.add(Check("host-stats-api", "PASS", f"/api/host/stats ok cpu={cpu if cpu is not None else '?'}"))
        ollama = host_stats.get("ollama")
        if ollama is None:
            result.add(
                Check(
                    "host-stats-ollama-schema",
                    "PASS",
                    "API omitted stats.ollama (external-agents) — HostStatsPage must not dereference stats.ollama.api_ok",
                )
            )
        elif isinstance(ollama, dict):
            result.add(
                Check(
                    "host-stats-ollama-schema",
                    "PASS",
                    f"ollama object present api_ok={ollama.get('api_ok')}",
                )
            )
        else:
            result.add(
                Check(
                    "host-stats-ollama-schema",
                    "FAIL",
                    f"unexpected stats.ollama type={type(ollama).__name__}",
                    product_bug=True,
                )
            )
    else:
        err = host_stats.get("error") if isinstance(host_stats, dict) else str(host_stats)
        result.add(Check("host-stats-api", "FAIL", f"HTTP {st} {err}", product_bug=True))

    st, model_before = client.get("/api/model/commissioning-export")
    client.save_json(out_dir / "model_commissioning_export_before.json", st, model_before)
    active = ""
    if isinstance(model_before, dict):
        sites = model_before.get("sites") or []
        if sites:
            active = sites[0].get("site_id") or ""
    stale = active == "site:import" or any(
        "import" in str(a.get("haystack_id", ""))
        for a in (model_before.get("assignments") or [])
        if isinstance(a, dict)
    )
    if stale:
        result.add(
            Check(
                "model-pre-state",
                "FAIL",
                f"stale CSV model active_site={active or 'site:import'} — agent bootstrap will attempt replace",
                product_bug=True,
            )
        )
    else:
        result.add(Check("model-pre-state", "PASS", f"active_site={active or 'unknown'}"))

    payload = build_agent_commissioning_payload(cfg)
    write_sql_artifact(
        out_dir,
        payload["fdd_rules"][0]["sql"],
        {"rule_id": cfg["fault_rule_id"], "site_id": cfg["site_id"], "equip_id": cfg["equip_id"]},
    )

    if not skip_import:
        st, imp = client.post("/api/model/commissioning-import", {"payload": payload})
        client.save_json(out_dir / "commissioning_import.json", st, imp)
        if st == 200 and isinstance(imp, dict) and imp.get("ok"):
            result.add(
                Check(
                    "commissioning-import",
                    "PASS",
                    f"sites={imp.get('sites')} equip={imp.get('equipment')} points={imp.get('points')} rules={imp.get('fdd_rules_updated')}",
                )
            )
        else:
            err = imp.get("error") if isinstance(imp, dict) else str(imp)
            result.add(
                Check(
                    "commissioning-import",
                    "FAIL",
                    f"HTTP {st} {err}",
                    product_bug=classify_product_bug("commissioning-import", str(err)),
                )
            )
            st2, sync = client.post("/api/model/sync-ttl", {})
            client.save_json(out_dir / "sync_ttl_fallback.json", st2, sync)

        st, sync = client.post("/api/model/sync-ttl", {})
        client.save_json(out_dir / "sync_ttl.json", st, sync)
    else:
        result.add(Check("commissioning-import", "SKIP", "OPENFDD_SKIP_COMMISSIONING_IMPORT=1"))

    rule = payload["fdd_rules"][0]
    st, saved = client.post(
        "/api/fdd-rules",
        {
            "rule_id": rule["rule_id"],
            "name": rule["name"],
            "sql": rule["sql"],
            "equipment_id": rule["equipment_id"],
            "site_id": rule["site_id"],
            "confirmation_seconds": rule["confirmation_seconds"],
            "severity": rule["severity"],
            "output_fault_code": rule["output_fault_code"],
            "review_status": "approved",
        },
    )
    client.save_json(out_dir / "fdd_rule_save.json", st, saved)
    if st == 200 and isinstance(saved, dict) and saved.get("ok"):
        result.add(Check("fdd-rule-save", "PASS", f"rule_id={rule['rule_id']}"))
    else:
        err = saved.get("error") if isinstance(saved, dict) else str(saved)
        result.add(Check("fdd-rule-save", "FAIL", f"HTTP {st} {err}", product_bug=True))

    st, validated = client.post(f"/api/fdd-rules/{rule['rule_id']}/validate-sql", {"sql": rule["sql"]})
    client.save_json(out_dir / "fdd_rule_validate_sql.json", st, validated)
    if st == 200 and isinstance(validated, dict) and validated.get("ok", True):
        result.add(Check("fdd-rule-validate-sql", "PASS", "SQL safety check ok"))
    else:
        err = validated.get("error") if isinstance(validated, dict) else str(validated)
        result.add(Check("fdd-rule-validate-sql", "FAIL", str(err), product_bug=True))

    st, activated = client.post(f"/api/fdd-rules/{rule['rule_id']}/activate", {})
    client.save_json(out_dir / "fdd_rule_activate.json", st, activated)
    if st == 200 and isinstance(activated, dict) and activated.get("ok"):
        result.add(Check("fdd-rule-activate", "PASS", f"activated {rule['rule_id']}"))
    else:
        err = activated.get("error") if isinstance(activated, dict) else str(activated)
        result.add(Check("fdd-rule-activate", "FAIL", str(err), product_bug=True))

    baseline = historian_snapshot(client)
    baseline_rows = int(baseline.get("row_count") or 0)
    client.save_json(out_dir / "historian_before_poll.json", 200, baseline)

    commission = OpenFddClient(cfg["commission"], client.token)
    st, modbus = client.post(
        "/api/modbus/read",
        {"register": 30001, "function": "input_register", "scale": 0.1, "unit": "degF"},
    )
    client.save_json(out_dir / "modbus_read.json", st, modbus)
    if st == 200 and isinstance(modbus, dict) and modbus.get("ok") and modbus.get("value") is not None:
        result.add(Check("modbus-read", "PASS", f"value={modbus.get('value')} {modbus.get('unit', 'degF')}"))
    else:
        result.add(Check("modbus-read", "FAIL", str(modbus.get("error") if isinstance(modbus, dict) else modbus), product_bug=True))

    st, whois = commission.post("/api/bacnet/whois", {"low_limit": 0, "high_limit": 4194303})
    client.save_json(out_dir / "bacnet_whois.json", st, whois)
    st, bacnet = commission.post(
        "/api/bacnet/read",
        {"point_id": f"bacnet:{cfg.get('bacnet_device', 5007)}:analog-input:1173"},
    )
    client.save_json(out_dir / "bacnet_read.json", st, bacnet)
    if st == 200 and isinstance(bacnet, dict) and (
        bacnet.get("ok") or bacnet.get("value") is not None or bacnet.get("present_value") is not None
    ):
        val = bacnet.get("present_value") or bacnet.get("value")
        result.add(Check("bacnet-read", "PASS", f"present_value={val}"))
    else:
        err = bacnet.get("error") if isinstance(bacnet, dict) else str(bacnet)
        result.add(Check("bacnet-read", "FAIL", str(err), product_bug=classify_product_bug("bacnet-read", str(err))))

    st, haystack = client.post("/api/haystack/test", {})
    client.save_json(out_dir / "haystack_test.json", st, haystack)
    if isinstance(haystack, dict) and haystack.get("ok") and haystack.get("enabled"):
        result.add(Check("haystack-test", "PASS", haystack.get("message", "connected")))
    elif isinstance(haystack, dict) and haystack.get("enabled") is False:
        result.add(Check("haystack-test", "SKIP", "Haystack disabled on bench (driver/TOML/firewall)"))
    else:
        result.add(Check("haystack-test", "FAIL", str(haystack.get("message") if isinstance(haystack, dict) else haystack), product_bug=True))

    st, json_once = client.post("/api/json-api/poll-once", json_api_poll_body(root))
    client.save_json(out_dir / "json_api_poll_once.json", st, json_once)
    http_ok = isinstance(json_once, dict) and (
        json_once.get("http_status") == 200 or json_once.get("ok") is True
    )
    if http_ok:
        result.add(Check("json-api-poll-once", "PASS", f"HTTP {json_once.get('http_status', 200)}"))
    else:
        result.add(Check("json-api-poll-once", "FAIL", str(json_once.get("error") if isinstance(json_once, dict) else json_once)))

    for _ in range(2):
        client.post("/api/modbus/poll/once", {})
        commission.post("/api/bacnet/whois", {"low_limit": 0, "high_limit": 4194303})
        time.sleep(5)

    st, poll_status = client.get("/api/modbus/poll/status")
    client.save_json(out_dir / "modbus_poll_status.json", st, poll_status)
    samples = int(poll_status.get("samples") or 0) if isinstance(poll_status, dict) else 0
    if samples > 0:
        result.add(Check("modbus-poll-samples", "PASS", f"samples={samples}"))
    else:
        result.add(
            Check(
                "modbus-poll-samples",
                "FAIL",
                f"samples={samples} enabled_points={poll_status.get('enabled_points') if isinstance(poll_status, dict) else '?'} — product poll loop not persisting",
                product_bug=True,
            )
        )

    wait_sec = int(os.environ.get("OPENFDD_BOOTSTRAP_HISTORIAN_WAIT_SEC", "90"))
    grew, hist_after = wait_for_historian_growth(client, baseline_rows, timeout_sec=wait_sec)
    client.save_json(out_dir / "historian_after_poll.json", 200, hist_after)
    rows = int(hist_after.get("row_count") or 0)
    if grew:
        result.add(Check("historian-growth", "PASS", f"rows {baseline_rows} → {rows}"))
    else:
        result.add(
            Check(
                "historian-growth",
                "FAIL",
                f"rows stuck at {rows} (baseline {baseline_rows}) — poll not appending telemetry_pivot",
                product_bug=True,
            )
        )

    st, model_after = client.get("/api/model/commissioning-export")
    client.save_json(out_dir / "model_commissioning_export_after.json", st, model_after)
    st2, assign_after = client.get("/api/model/assignments")
    client.save_json(out_dir / "model_assignments_after.json", st2, assign_after)
    rules_count = len(model_after.get("fdd_rules") or []) if isinstance(model_after, dict) else 0
    assign_count = len(model_after.get("assignments") or []) if isinstance(model_after, dict) else 0
    points_count = len(model_after.get("points") or []) if isinstance(model_after, dict) else 0
    active_site = ""
    if isinstance(model_after, dict) and model_after.get("sites"):
        active_site = model_after["sites"][0].get("site_id") or ""
    if assign_count >= 2 and rules_count >= 1 and active_site == cfg["site_id"]:
        result.add(
            Check(
                "model-post-state",
                "PASS",
                f"site={active_site} assignments={assign_count} points={points_count} fdd_rules={rules_count}",
            )
        )
    elif assign_count >= 2 and rules_count >= 1:
        result.add(
            Check(
                "model-post-state",
                "FAIL",
                f"partial model site={active_site or '?'} assignments={assign_count} rules={rules_count} — active site not {cfg['site_id']}",
                product_bug=True,
            )
        )
    else:
        result.add(
            Check(
                "model-post-state",
                "FAIL",
                f"assignments={assign_count} points={points_count} fdd_rules={rules_count} site={active_site or '?'} — expected OT model + SQL rule after bootstrap",
                product_bug=True,
            )
        )

    st, rules = client.get("/api/fdd-rules")
    client.save_json(out_dir / "fdd_rules_list.json", st, rules)
    st, batch = client.post("/api/rules/batch", {})
    client.save_json(out_dir / "fdd_batch_run.json", st, batch)
    if st == 200 and isinstance(batch, dict) and batch.get("ok", True):
        result.add(Check("fdd-batch-run", "PASS", f"rules_run={batch.get('rules_run', batch.get('count', '?'))}"))
    else:
        result.add(Check("fdd-batch-run", "FAIL", str(batch.get("error") if isinstance(batch, dict) else batch), product_bug=True))

    result.finalize()
    result.write(out_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-FDD agent bootstrap validation")
    parser.add_argument("--out", default=os.environ.get("OPENFDD_FRONTEND_ARTIFACT_DIR", ""))
    args = parser.parse_args()
    out = Path(args.out) if args.out else bench_root() / "workspace/logs/frontend_bootstrap_latest"
    skip = os.environ.get("OPENFDD_SKIP_COMMISSIONING_IMPORT", "0") == "1"
    log(f"agent bootstrap → {out}")
    result = run_bootstrap(out, skip_import=skip)
    log(f"done pass={result.pass_count} fail={result.fail_count} skip={result.skip_count}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
