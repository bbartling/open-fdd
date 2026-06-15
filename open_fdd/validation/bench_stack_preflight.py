"""Stack + FDD rules preflight for Bench 5007 / benserver smokes."""

from __future__ import annotations

from typing import Any, Callable

FetchFn = Callable[[str, str, dict | None], tuple[int, Any]]

BENCH_RULE_IDS: tuple[str, ...] = (
    "temp-out-of-bounds",
    "temp-rate-of-change",
    "humidity-out-of-bounds",
    "humidity-rate-of-change",
)

EXPECTED_POINT_BINDINGS: dict[str, int] = {
    "temp-out-of-bounds": 6,
    "temp-rate-of-change": 6,
    "humidity-out-of-bounds": 2,
    "humidity-rate-of-change": 2,
}


def validate_rules_in_service(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Match Rule Lab / FDD rules in service panel: enabled + point bindings."""
    enabled = [r for r in rules if isinstance(r, dict) and r.get("enabled", True)]
    by_id = {str(r.get("id") or ""): r for r in enabled}
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    missing = [rid for rid in BENCH_RULE_IDS if rid not in by_id]
    if missing:
        errors.append(f"missing enabled bench rules: {missing}")

    arrow_count = 0
    sql_count = 0
    bound_with_points = 0
    for rid in BENCH_RULE_IDS:
        rule = by_id.get(rid)
        if not rule:
            continue
        backend = str(rule.get("backend") or "arrow")
        if backend == "datafusion_sql":
            sql_count += 1
        else:
            arrow_count += 1
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        pids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
        expected = EXPECTED_POINT_BINDINGS.get(rid, 0)
        if len(pids) != expected:
            errors.append(f"{rid}: expected {expected} point bindings, got {len(pids)}")
        elif pids:
            bound_with_points += 1
        checks.append(
            {
                "rule_id": rid,
                "backend": backend,
                "point_bindings": len(pids),
                "enabled": True,
            }
        )

    if bound_with_points != len(BENCH_RULE_IDS):
        errors.append(f"expected {len(BENCH_RULE_IDS)} rules with point bindings, got {bound_with_points}")

    return {
        "ok": not errors,
        "errors": errors,
        "enabled_count": len(enabled),
        "bound_count": bound_with_points,
        "arrow_rules": arrow_count,
        "datafusion_sql_rules": sql_count,
        "checks": checks,
    }


def validate_stack_preflight(
    fetch: FetchFn,
    token: str,
    *,
    model: dict[str, Any] | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Health, building snapshot, bench health, and four bench FDD rules."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    status, health = fetch("GET", "/health", None)
    checks.append({"name": "bridge_health", "http": status, "ok": status == 200 and isinstance(health, dict) and health.get("ok")})
    if not checks[-1]["ok"]:
        errors.append(f"bridge /health failed HTTP {status}")

    status, snap = fetch("GET", "/api/building/snapshot", token)
    snap_ok = status == 200 and isinstance(snap, dict) and snap.get("ok") and isinstance(snap.get("stack"), dict)
    checks.append({"name": "building_snapshot", "http": status, "ok": snap_ok})
    if not snap_ok:
        errors.append(f"/api/building/snapshot failed HTTP {status}")

    status, bench = fetch("GET", "/api/bench/health", token)
    bench_ok = status == 200 and isinstance(bench, dict) and bench.get("ok")
    checks.append({"name": "bench_health", "http": status, "ok": bench_ok})
    if not bench_ok:
        errors.append(f"/api/bench/health failed HTTP {status}")

    if rules is None:
        status, body = fetch("GET", "/api/rules/saved", token)
        if status != 200 or not isinstance(body, dict):
            errors.append(f"/api/rules/saved failed HTTP {status}")
            rules = []
        else:
            rules = body.get("rules") or []

    rules_report = validate_rules_in_service(rules if isinstance(rules, list) else [])
    checks.append({"name": "fdd_rules_in_service", "ok": rules_report["ok"], **rules_report})
    errors.extend(rules_report.get("errors") or [])

    if model is not None and rules:
        try:
            from openfdd_bridge.bench_contract import validate_bench_contract

            contract = validate_bench_contract(model, rules, require_four_rules=True)
            checks.append({"name": "bench_contract", "ok": contract.get("ok"), "issues": contract.get("issues") or []})
            if not contract.get("ok"):
                for issue in contract.get("issues") or []:
                    errors.append(f"bench contract: {issue}")
        except ImportError:
            warnings.append("bench_contract import skipped (openfdd_bridge not on path)")

    status, batch = fetch("POST", "/api/rules/batch", {"limit": 10})
    batch_ok = status == 200 and isinstance(batch, dict)
    runs = batch.get("runs") or [] if isinstance(batch, dict) else []
    run_errors = [str(r.get("error") or "") for r in runs if isinstance(r, dict) and r.get("status") == "error"]
    checks.append(
        {
            "name": "fdd_batch",
            "http": status,
            "ok": batch_ok and len(runs) >= 4 and not run_errors,
            "run_count": len(runs),
            "flagged": sum(int(r.get("flagged") or 0) for r in runs if isinstance(r, dict)),
        }
    )
    if not batch_ok:
        errors.append(f"/api/rules/batch failed HTTP {status}")
    elif len(runs) < 4:
        errors.append(f"FDD batch expected 4+ runs, got {len(runs)}")
    elif run_errors:
        errors.append(f"FDD batch errors: {run_errors[:3]}")

    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "rules": rules_report,
    }
