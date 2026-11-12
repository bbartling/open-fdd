"""The shared core schema (sql/fdd/schema/core.sql) has one source and cannot drift."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/nf"))

import build_core_schema as core  # noqa: E402
from input_contract import input_sample_signature, load_source  # noqa: E402

CORE_TABLES = ("fdd.point", "fdd.rule_config", "fdd.rule_result")
needs_node = pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "nf-app/node_modules/@electric-sql").is_dir(),
                                reason="node and the nf-app dependencies (PGlite) are required")


def norm(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_copies_are_byte_identical_to_the_source():
    source = norm(core.SOURCE)
    assert source.startswith(b"-- Open-FDD core schema, core_version 4")
    for copy in core.COPIES:
        assert norm(copy) == source, f"{copy.relative_to(ROOT)} differs from sql/fdd/schema/core.sql"


def test_core_has_no_policy_and_install_files_define_no_core_table():
    text = core.SOURCE.read_text(encoding="utf-8")
    assert "create_hypertable" not in text.lower()
    assert "fdd.sample" not in text and "input_sample" not in re.sub(r"--.*", "", text)
    for name in ("install.sql", "adapter_nf.sql"):
        body = re.sub(r"--.*", "", (ROOT / "nf-app/timescale" / name).read_text(encoding="utf-8"))
        assert not re.search(r"create\s+table\s+(if\s+not\s+exists\s+)?fdd\.", body, re.I), f"{name} must not create fdd tables"


def test_wheel_ships_the_core():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"data/*.sql"' in pyproject
    assert (ROOT / "open_fdd/data/core.sql").is_file()


def test_tuning_storage_is_only_a_pointer():
    text = (ROOT / "sql/fdd/tuning_storage.sql").read_text(encoding="utf-8")
    assert "schema/core.sql" in text
    assert not re.search(r"^\s*(create|alter|drop)\b", text, re.I | re.M)


@needs_node
def test_catalog_equals_what_postgres_reports():
    stored = json.loads(core.CATALOG.read_text(encoding="utf-8"))
    assert stored["core_sql_sha256"] == core.sha256_of(core.source_bytes())
    live = core.pg_catalog(core.SOURCE)
    assert set(stored["tables"]) == set(CORE_TABLES)
    assert {k: v for k, v in live.items() if k.startswith("fdd.")} == stored["tables"]
    assert live["_relations"] == ["point", "rule_config", "rule_result"]     # nothing else is created


@needs_node
def test_catalog_pins_the_keys_downstream_relies_on():
    tables = json.loads(core.CATALOG.read_text(encoding="utf-8"))["tables"]
    primary = {t: next(c["definition"] for c in v["constraints"] if c["type"] == "p") for t, v in tables.items()}
    assert primary["fdd.point"] == "PRIMARY KEY (site_id, point_key)"
    assert primary["fdd.rule_result"] == ("PRIMARY KEY (site_id, equipment_id, rule_id, subject_key, window_start, window_end, "
                                          "rule_hash, config_hash)")
    assert primary["fdd.rule_config"] == "PRIMARY KEY (site_id, rule_id, scope_key, revision)"
    status = next(c["definition"] for c in tables["fdd.rule_result"]["constraints"] if "status" in c["definition"])
    for value in ("PASS", "FAULT", "INCONCLUSIVE", "SKIPPED", "ERROR", "STALE"):
        assert f"'{value}'" in status


def test_build_script_check_passes():
    if shutil.which("node") is None or not (ROOT / "nf-app/node_modules/@electric-sql").is_dir():
        pytest.skip("node and the nf-app dependencies (PGlite) are required")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/nf/build_core_schema.py"), "--check"], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout


def test_input_contract_declares_the_input_sample_signature():
    source = load_source()
    assert source["version"] == 3
    assert input_sample_signature() == [("site_id", "text"), ("point_key", "text"),
                                        ("ts", "timestamp with time zone"), ("value", "double precision")]
    assert source["sources"]["point"]["key"] == ["site_id", "point_key"]
