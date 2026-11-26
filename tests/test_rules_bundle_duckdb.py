"""The versioned rules zip is the full SQL catalog, and DuckDB runs every rendered rule offline."""
from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_rules_bundle", ROOT / "scripts" / "nf" / "build_rules_bundle.py"
)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

ADAPTERS = importlib.util.spec_from_file_location(
    "parity_adapters", ROOT / "tests" / "parity" / "adapters.py"
)
adapters = importlib.util.module_from_spec(ADAPTERS)
ADAPTERS.loader.exec_module(adapters)


def _statements(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            text = "\n".join(buf).strip().rstrip(";").strip()
            if text:
                parts.append(text)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        parts.append(tail)
    return parts


def test_zip_pins_full_sql_tree_and_confirm_min(tmp_path):
    dest = bundle.build_bundle(tmp_path / "open-fdd-rules.zip")
    with zipfile.ZipFile(dest) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        pack = json.loads(archive.read("pack.json"))
        stored = {name: archive.read(name) for name in names if name != "manifest.json"}

    sql_on_disk = [path.relative_to(ROOT).as_posix() for path in bundle.sql_files()]
    assert sql_on_disk, "sql/ is empty"
    assert len(sql_on_disk) > 5
    # The archive is the whole tree, not the five sensor-sweep templates.
    assert "sql/fdd/postgres/rules/fc1_duct_static_low.sql" in sql_on_disk
    assert "sql/analytics/anomaly_zscore.sql" in sql_on_disk
    assert "sql/fdd/postgres/rules/sv_range.sql" in sql_on_disk
    missing = [name for name in sql_on_disk if name not in names]
    assert missing == []
    extra = [name for name in names if name.startswith("sql/") and name not in sql_on_disk]
    assert extra == []
    for name in sql_on_disk:
        assert stored[name] == (ROOT / name).read_bytes()

    assert manifest["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert manifest["rule_count"] == 78
    assert manifest["user_tuners"] == [
        {"key": "confirm_min", "default": 15, "unit": "min", "min": 0, "max": 60}
    ]
    assert [tuner["key"] for tuner in manifest["user_tuners"]] == ["confirm_min"]
    assert manifest["files"]["pack.json"]["sha256"]
    for name in sql_on_disk:
        assert manifest["files"][name]["bytes"] == len(stored[name])

    assert pack["rule_count"] == 78
    assert pack["confirm_min"] == 15
    assert len(pack["rules"]) == 78
    import yaml

    registry = yaml.safe_load((ROOT / "sql/fdd/registry.yaml").read_text(encoding="utf-8"))
    assert set(pack["rules"]) == {rule["rule_id"] for rule in registry["rules"]}
    tuning = json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))
    by_id = {rule["rule_id"]: rule for rule in tuning["rules"]}
    assert pack["rules"]["FC1"]["confirm_min"] == 15
    assert pack["rules"]["FC1"]["sql"] == bundle._render()("FC1", 300, {"confirm_min": 15})
    assert pack["rules"]["SV-STALE"]["confirm_min"] is None
    assert pack["rules"]["SV-STALE"]["sql"] == bundle._render()("SV-STALE", 300, None)
    baked = sum(1 for rule in pack["rules"].values() if rule["confirm_min"] == 15)
    assert baked == sum(1 for rule in by_id.values() if "confirm_min" in rule["parameters"])
    assert "sql/fdd/schema/core.sql" in names


def test_pack_runs_on_memory_duckdb_without_extension_autoinstall(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    dest = bundle.build_bundle(tmp_path / "open-fdd-rules.zip")
    with zipfile.ZipFile(dest) as archive:
        pack = json.loads(archive.read("pack.json"))
        ddl = archive.read("sql/fdd/input_contract.sql").decode("utf-8")

    con = duckdb.connect(
        ":memory:",
        config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    )
    try:
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("SET autoload_known_extensions = false")
        autoinstall = con.execute("SELECT current_setting('autoinstall_known_extensions')").fetchone()[0]
        autoload = con.execute("SELECT current_setting('autoload_known_extensions')").fetchone()[0]
        assert autoinstall in (False, "false", 0)
        assert autoload in (False, "false", 0)
        con.execute("SET TimeZone = 'UTC'")
        for statement in _statements(adapters.DUCKDB_HELPERS_SQL):
            con.execute(statement)
        for statement in _statements(ddl):
            con.execute(statement)
        failures = []
        assert len(pack["rules"]) == 78
        for rule_id, rule in pack["rules"].items():
            try:
                cur = con.execute(rule["sql"])
                rows = cur.fetchall()
            except Exception as exc:  # noqa: BLE001 — report every rule, then fail once
                failures.append(f"{rule_id}: {exc}")
                continue
            assert rows == [] or rows is not None
        assert failures == [], failures
    finally:
        con.close()
