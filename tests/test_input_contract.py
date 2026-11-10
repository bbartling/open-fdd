import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/nf"))

from input_contract import load_contract, load_source  # noqa: E402
from build_sql_pack import parse_contract  # noqa: E402


def test_every_role_has_a_typed_history_column_and_scale():
    source = load_source()
    contract = load_contract()
    roles = source["roles"]
    history = {col["name"]: col for col in contract["history"]}
    source_history = {col["name"]: col for col in source["_normalized_tables"]["history"]}
    assert set(history) == set(roles) | {"equipment_id", "timestamp_utc"}
    for role, spec in roles.items():
        assert history[role]["type"] == spec["type"]
        assert source_history[role]["role"] == role


def test_contract_declares_metadata_relations_and_every_rule_relation():
    contract = load_contract()
    assert set(contract) == {
        "history", "weather", "utility_interval", "utility_monthly", "authorized_series", "equipment", "sensor_history",
    }
    assert {"site_id", "equipment_id", "role", "unit"} <= {c["name"] for c in contract["authorized_series"]}
    assert {"building_id", "equipment_id"} <= {c["name"] for c in contract["equipment"]}

    sv_sql = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "sql/fdd/postgres/rules").glob("sv_*.sql"))
    assert sv_sql.count("sensor_series AS (") == 5
    assert re.search(r"\bseries_id\b", sv_sql, re.I)
    assert re.search(r"\bsensor_role\b", sv_sql, re.I)


def test_standalone_ddl_and_role_scale_compatibility_are_generated():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/nf/build_input_contract.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    scale_view = json.loads((ROOT / "sql/fdd/role_scales.json").read_text(encoding="utf-8"))
    source = load_source()
    assert scale_view["roles"] == {r: spec["scale"] for r, spec in source["roles"].items()}


def test_pack_contract_has_no_builder_only_supplementary_inputs():
    assert parse_contract() == load_contract()
