import json
from pathlib import Path
from types import SimpleNamespace

from open_fdd.reporting.narrative_polish import polish_sensor_paragraph
from open_fdd.reporting.single_system_typst import sensor_validation_bullets


def test_sensor_sweep_reports_missing_samples_separately_from_range_faults():
    result = SimpleNamespace(
        rule_id="SV-RANGE",
        status="FAULT",
        fault_hours=2,
        confirmed_fault=[True],
        metrics={
            "sv_sweep_evidence": [
                {"role": "sat", "faulted": True, "fault_hours": 2, "silence_hours": 2},
                {"role": "rat", "faulted": True, "fault_hours": 1, "silence_hours": 0},
            ]
        },
    )
    checks = sensor_validation_bullets([result], [])
    assert [check["roles"] for check in checks] == [["sat"], ["rat"]]
    assert checks[0]["silence_hours"] == 2
    text = polish_sensor_paragraph(checks)
    assert "had gaps in reporting." in text
    assert "read outside its physical range." in text
    assert text.count("physical range") == 1


def test_sensor_sweep_packs_expose_the_same_hours_and_sensor_identity_contract():
    root = Path(__file__).resolve().parents[1]
    for dialect in ("postgres", "sqlite"):
        pack = json.loads((root / "nf-app" / "rules" / f"pack-{dialect}.json").read_text(encoding="utf-8"))
        for suffix in ("STALE", "FLATLINE", "RANGE", "SPIKE", "RATE"):
            rule = pack["rules"][f"SV-{suffix}"]
            assert rule["output_columns"] == [
                "equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours",
            ]


def test_assessable_sensor_roles_are_shared_by_sql_pandas_and_hook():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / "open_fdd/data/sensor_sweep_roles.json").read_text(encoding="utf-8"))
    role_map = json.loads((root / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
    inverse = {name: role for role, name in role_map.items()}
    expected_sql = {rule: [inverse[name] for name in roles] for rule, roles in source.items()}
    catalog = json.loads((root / "nf-app/static/fdd-catalog.json").read_text(encoding="utf-8"))
    assert catalog["sensor_sweep_roles"] == expected_sql

    from open_fdd.rules.sensor_sweep_catalog import ASSESSABLE_ROLES_BY_SWEEP

    assert {rule: list(roles) for rule, roles in ASSESSABLE_ROLES_BY_SWEEP.items()} == source
    assert all("zone-airflow" not in roles for roles in source.values())
    assert {rule for rule, roles in source.items() if "duct-static-pressure" in roles} == {"SV-RANGE", "SV-SPIKE"}

    pack = json.loads((root / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
    for rule in ("SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE"):
        template = (root / "sql/fdd/postgres/rules" / f"{rule.lower().replace('-', '_')}.sql").read_text(encoding="utf-8")
        assert template.count("{{ASSESSABLE_ROLES}}") == 2, rule
        sql = pack["rules"][rule]["sql"]
        assert "{{ASSESSABLE_ROLES}}" not in sql, rule
        allowed = ", ".join(f"'{role}'" for role in expected_sql[rule])
        assert sql.count(f"sensor_role IN ({allowed})") == 2, rule
