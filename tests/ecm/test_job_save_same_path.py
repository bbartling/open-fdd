"""BUG-OFDD-ECM-002 — ECMJob.save same-path must not raise SameFileError."""

from __future__ import annotations

from pathlib import Path

from open_fdd.ecm_engineering import ECMJob


def test_save_same_path_idempotent(tmp_path: Path) -> None:
    name = "Lincoln Middle School"
    # Keep CWD under tmp so default slug path is isolated
    out = tmp_path / "Lincoln_Middle_School_ECMs.xlsx"
    job = (
        ECMJob(name, path=out)
        .set_global(area_ft2=85000, electric_rate=0.145, gas_rate=0.92)
        .add_ecm(
            "static_pressure_reset",
            fan_kw=55.9,
            hours=4100,
            baseline_speed=0.82,
            proposed_speed=0.67,
        )
        .add_ecm(
            "boiler_reset",
            base_therms=48000,
            base_eff=0.86,
            prop_eff=0.92,
        )
    )
    path = job.save(str(out))
    assert path.resolve() == out.resolve()
    assert out.is_file() and out.stat().st_size > 0
    path2 = job.save()
    assert path2.resolve() == out.resolve()
    path3 = job.save(str(out))
    assert path3.resolve() == out.resolve()


def test_save_copy_to_other_path(tmp_path: Path) -> None:
    src = tmp_path / "job.xlsx"
    dst = tmp_path / "copy.xlsx"
    job = ECMJob("Copy Test", path=src).set_global(electric_rate=0.12)
    job.add_ecm(
        "static_pressure_reset",
        fan_kw=10.0,
        hours=1000,
        baseline_speed=0.8,
        proposed_speed=0.7,
    )
    job.save(dst)
    assert dst.is_file() and dst.stat().st_size > 0
    assert src.is_file()
