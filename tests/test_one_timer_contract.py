"""#1671: at most one user-facing delay/duration timer per rule; retired keys are fixed internal constants."""

import json
from pathlib import Path

import pytest

from sql.fdd.render_rule import render

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]
TIME_UNITS = {"min", "h", "s", "sec"}
RETIRED = {"startup_delay_min", "mode_delay_min", "minimum_active_coverage_pct", "minimum_coverage_pct",
           "require_operational_gate", "web_asof_margin_seconds", "web_cadence_seconds", "max_silence_hours",
           "persistence_min", "max_gap_hours"}


def test_at_most_one_time_control_per_rule():
    for rule in CATALOG:
        timers = [k for k, p in rule["parameters"].items() if p.get("unit") in TIME_UNITS]
        assert len(timers) <= 1, f"{rule['rule_id']}: {timers}"


def test_retired_keys_are_not_controls_and_are_listed_as_retired():
    for rule in CATALOG:
        exposed = RETIRED & set(rule["parameters"])
        assert not exposed, f"{rule['rule_id']} still exposes {sorted(exposed)}"
        for key in RETIRED & set((rule.get("legacy_parameters") or {}).get("retired", [])):
            with pytest.raises(ValueError, match="retired"):
                render(rule["rule_id"], overrides={key: 1.0})


def test_internal_constants_are_the_shipped_defaults():
    """The retired controls are pinned at the values the SQL already used, so the rendered rules do not change."""
    pack = json.loads((ROOT / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
    for rule in CATALOG:
        if rule.get("internal_constants"):
            assert render(rule["rule_id"], 300) == pack["rules"][rule["rule_id"]]["sql"], rule["rule_id"]
    fc1 = next(r for r in CATALOG if r["rule_id"] == "FC1")["internal_constants"]
    assert fc1["MODE_DELAY_MIN"] == 10.0 and fc1["STARTUP_DELAY_MIN"] == 0.0 and fc1["MINIMUM_ACTIVE_COVERAGE_PCT"] == 5.0
    meteo = next(r for r in CATALOG if r["rule_id"] == "OAT-METEO")["internal_constants"]
    assert meteo == {"WEB_ASOF_MARGIN_SECONDS": 300.0, "WEB_CADENCE_SECONDS": 1200.0}


def test_window_rules_keep_only_the_window_duration():
    by_id = {r["rule_id"]: r for r in CATALOG}
    for rule_id, window in {"SV-FLATLINE": "flatline_hours", "VAV-4": "sustain_hours", "VAV-7": "fixed_flow_hours",
                            "PID-HUNT-1": "window_hours"}.items():
        rule = by_id[rule_id]
        assert window in rule["parameters"] and "confirm_min" not in rule["parameters"]
        assert rule["internal_constants"]["CONFIRM_SECONDS"] == rule["confirm_seconds"]
