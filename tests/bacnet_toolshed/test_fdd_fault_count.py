import json

from bacnet_toolshed.fdd_fault_count import active_fdd_fault_count


def test_active_fdd_fault_count(tmp_path):
    data_dir = tmp_path / "workspace" / "data"
    data_dir.mkdir(parents=True)
    doc = {
        "runs": [
            {"status": "ok", "flagged": 3},
            {"status": "ok", "flagged": 0},
            {"status": "error"},
        ]
    }
    (data_dir / "fdd_results.json").write_text(json.dumps(doc), encoding="utf-8")
    assert active_fdd_fault_count(tmp_path) == 2
