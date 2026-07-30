"""BUG-OFDD-ECM-007 — chiller_lockout / load_shed / schedule_align modules."""

from __future__ import annotations

from pathlib import Path

from open_fdd.ecm_engineering import ECMJob, list_ecm_modules


def test_new_modules_in_list() -> None:
    mods = list_ecm_modules()
    assert "chiller_lockout" in mods
    assert "load_shed" in mods
    assert "schedule_align" in mods
    assert "ahu_sched_align" in mods


def test_add_ecm_new_modules(tmp_path: Path) -> None:
    job = ECMJob("007", path=tmp_path / "m.xlsx")
    job.add_ecm("chiller_lockout", plant_kw=150.0, lockout_hours=600.0, cost=2500.0)
    job.add_ecm(
        "load_shed",
        plant_kw=150.0,
        kw_fraction=0.13,
        loadshed_hours=2.0,
        cost=1500.0,
    )
    job.add_ecm(
        "schedule_align",
        fan_kw=40.0,
        plant_kw=150.0,
        sched_hours_saved=1000.0,
        cost=8000.0,
    )
    job.add_ecm("ahu_sched_align")  # alias, no kwargs
    selected = job.selected_modules()
    assert "ECM_Chiller_Lockout" in selected
    assert "ECM_Load_Shed" in selected
    assert "ECM_Schedule_Align" in selected
    job.save()
    assert (tmp_path / "m.xlsx").is_file()
