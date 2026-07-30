"""BUG-OFDD-ECM-003 / 012 — list_ecm_modules vs calculators; friendly sat_reset."""

from __future__ import annotations

from pathlib import Path

from open_fdd.ecm_engineering import ECMJob, list_calculators, list_ecm_modules


def test_list_ecm_modules_disjoint_from_calculators() -> None:
    modules = list_ecm_modules()
    calcs = list_calculators()
    assert "static_pressure_reset" in modules
    assert "sat_reset" in modules
    assert "fan_affinity" in calcs
    assert "fan_affinity" not in modules
    assert modules == sorted(modules)


def test_add_ecm_from_list_ecm_modules(tmp_path: Path) -> None:
    name = list_ecm_modules()[0]
    job = ECMJob("t", path=tmp_path / "t.xlsx")
    job.add_ecm(name)  # no KeyError even with no kwargs
    assert job.selected_modules()


def test_sat_reset_friendly_kwargs(tmp_path: Path) -> None:
    job = ECMJob("sat", path=tmp_path / "sat.xlsx")
    job.add_ecm(
        "sat_reset",
        cool_kwh=100_000.0,
        reset_f=3.0,
        gain_per_f=0.02,
        realization=0.8,
        cost=5000.0,
    )
    assert "ECM_DAT_Reset" in job.selected_modules()
