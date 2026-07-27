from pathlib import Path
import zipfile
from open_fdd.ecm_engineering import ECMJob

def test_generate_workbook(tmp_path: Path):
    path = tmp_path / "job.xlsx"
    job = (
        ECMJob("School", path=path)
        .set_global(area_ft2=85000, electric_rate=0.145)
        .add_ecm(
            "static_pressure_reset",
            fan_kw=55.9,
            hours=4100,
            baseline_speed=0.82,
            proposed_speed=0.67,
        )
    )
    assert job.save() == path
    assert path.exists()
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert "xl/workbook.xml" in z.namelist()
