"""Tests for bench stack + FDD rules preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_fdd.validation.bench_stack_preflight import (
    BENCH_RULE_IDS,
    validate_rules_in_service,
    validate_stack_preflight,
)

REPO = Path(__file__).resolve().parents[3]
RULES_STORE = REPO / "workspace" / "data" / "rules_store.json"


def _bench_rules_fixture() -> list[dict]:
    """CI-safe fixture — mirrors benserver 4-rule bench bindings without gitignored data/."""

    def _rule(rule_id: str, point_count: int) -> dict:
        return {
            "id": rule_id,
            "enabled": True,
            "backend": "arrow",
            "bindings": {"point_ids": [f"bench-{rule_id}-{i}" for i in range(point_count)]},
        }

    return [
        _rule("temp-out-of-bounds", 6),
        _rule("temp-rate-of-change", 6),
        _rule("humidity-out-of-bounds", 2),
        _rule("humidity-rate-of-change", 2),
    ]


def _load_bench_rules() -> list[dict]:
    if RULES_STORE.is_file():
        return json.loads(RULES_STORE.read_text(encoding="utf-8")).get("rules") or []
    return _bench_rules_fixture()


def test_validate_rules_in_service_matches_ui_counts():
    rules = _bench_rules_fixture()
    report = validate_rules_in_service(rules)
    assert report["ok"] is True
    assert report["enabled_count"] == 4
    assert report["bound_count"] == 4
    assert report["arrow_rules"] == 4
    assert report["datafusion_sql_rules"] == 0
    by_id = {c["rule_id"]: c for c in report["checks"]}
    assert by_id["temp-out-of-bounds"]["point_bindings"] == 6
    assert by_id["humidity-out-of-bounds"]["point_bindings"] == 2


def test_validate_rules_in_service_live_store_includes_bench_rules():
    """Optional host check — skip when local rules_store is not the bench contract."""
    if not RULES_STORE.is_file():
        pytest.skip("no live rules_store.json")
    rules = _load_bench_rules()
    report = validate_rules_in_service(rules)
    if not report["ok"]:
        pytest.skip(f"live rules_store mismatch: {report.get('errors')}")
    assert report["bound_count"] == 4
    by_id = {c["rule_id"]: c for c in report["checks"]}
    for rid in BENCH_RULE_IDS:
        assert rid in by_id


def test_validate_rules_in_service_fails_when_rule_missing():
    rules = [{"id": "temp-out-of-bounds", "enabled": True, "bindings": {"point_ids": ["a"] * 6}}]
    report = validate_rules_in_service(rules)
    assert report["ok"] is False
    assert any("missing enabled" in e for e in report["errors"])


def test_validate_stack_preflight_happy_path():
    rules = _bench_rules_fixture()

    def fetch(method: str, path: str, body: dict | None = None):
        if path == "/health":
            return 200, {"ok": True}
        if path == "/api/building/snapshot":
            return 200, {"ok": True, "stack": {"status": "ok"}, "faults": {}}
        if path == "/api/bench/health":
            return 200, {"ok": True, "read_only": True}
        if path == "/api/rules/batch":
            return 200, {"runs": [{"status": "ok", "flagged": 1}] * 4}
        return 404, {}

    out = validate_stack_preflight(fetch, "token", rules=rules)
    assert out["ok"] is True
    names = {c["name"] for c in out["checks"]}
    assert names >= {"bridge_health", "building_snapshot", "bench_health", "fdd_rules_in_service", "fdd_batch"}


def test_validate_stack_preflight_snapshot_502():
    rules = [
        {
            "id": rid,
            "enabled": True,
            "bindings": {"point_ids": ["p"] * (6 if rid.startswith("temp") else 2)},
        }
        for rid in BENCH_RULE_IDS
    ]

    def fetch(method: str, path: str, body: dict | None = None):
        if path == "/health":
            return 200, {"ok": True}
        if path == "/api/building/snapshot":
            return 502, {"detail": "bad gateway"}
        if path == "/api/bench/health":
            return 200, {"ok": True}
        if path == "/api/rules/batch":
            return 200, {"runs": [{}] * 4}
        return 404, {}

    out = validate_stack_preflight(fetch, "token", rules=rules)
    assert out["ok"] is False
    assert any("building/snapshot" in e for e in out["errors"])
