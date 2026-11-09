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
