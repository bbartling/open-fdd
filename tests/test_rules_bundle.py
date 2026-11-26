"""#1806: the pinnable rules bundle is complete, reproducible and runs every rule offline on in-memory DuckDB.

Set ``RULES_BUNDLE_ZIP`` to test a prebuilt zip (the tag workflow does); otherwise a fresh bundle is built.
"""
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "tests" / "parity")):
    if p not in sys.path:
        sys.path.insert(0, p)
spec = importlib.util.spec_from_file_location("build_rules_bundle", ROOT / "scripts" / "build_rules_bundle.py")
bundle = importlib.util.module_from_spec(spec)
sys.modules["build_rules_bundle"] = bundle
spec.loader.exec_module(bundle)


@pytest.fixture(scope="module")
def unpacked(tmp_path_factory):
    out = tmp_path_factory.mktemp("rules-bundle")
    zpath = os.environ.get("RULES_BUNDLE_ZIP")
    if not zpath:
        assert bundle.main(["--out", str(out)]) == 0
        zpath = str(next(out.glob("open-fdd-rules-*.zip")))
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(out / "x")
    return out / "x"


@pytest.fixture(scope="module")
def manifest(unpacked):
    return json.loads((unpacked / "rules-manifest.json").read_text(encoding="utf-8"))


def test_check_mode_is_reproducible(tmp_path):
    assert bundle.main(["--check", "--out", str(tmp_path)]) == 0


def test_manifest_covers_every_pack_rule_and_input(manifest, unpacked):
    pack = json.loads((ROOT / "nf-app" / "rules" / "pack-postgres.json").read_text(encoding="utf-8"))
    assert sorted(r["rule_id"] for r in manifest["rules"]) == sorted(pack["rules"])
    assert manifest["rule_count"] == len(pack["rules"])
    assert bundle.validate(manifest) == []
    names = [v["name_223p"] for v in manifest["inputs"].values()]
    assert len(names) == len(set(names))
    for r in manifest["rules"]:
        assert r["title"] and isinstance(r["confirm_min"], (int, float))
        for i in r["inputs"]:
            assert i["unit"] and i["name_223p"] and i["role"] in manifest["inputs"], (r["rule_id"], i)
        for dialect in ("postgresql", "timescaledb", "duckdb"):
            assert (unpacked / r["dialects"][dialect]["file"]).is_file()
        assert "{{" not in (unpacked / r["dialects"]["duckdb"]["file"]).read_text(encoding="utf-8")
    other = manifest["confirm_min"]["rules_with_other_default"]
    assert {r["rule_id"] for r in manifest["rules"] if r["confirm_min"] != 15} == set(other)


def _offline_duckdb(unpacked):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    con.execute("SET TimeZone = 'UTC'")
    for f in ("schema/core.duckdb.sql", "schema/input_sample.sql", "helpers/duckdb.sql", "schema/inputs.sql"):
        con.execute((unpacked / f).read_text(encoding="utf-8"))
    con.execute("SET enable_external_access = false")   # no files, no network from here on
    return con


def test_schema_tables_exist_in_duckdb(unpacked):
    con = _offline_duckdb(unpacked)
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'fdd'").fetchall()}
    assert tables >= {"point", "input_sample", "rule_result", "rule_config"}
    con.execute("INSERT INTO fdd.rule_config (site_id, rule_id, scope_key, revision, parameters, active, created_by) "
                "VALUES ('', 'FC1', 'site', 1, '{\"confirm_min\": 15}', true, 'test')")
    assert con.execute("SELECT parameters->>'confirm_min' FROM fdd.rule_config").fetchone()[0] == "15"


def test_every_rule_runs_offline_on_duckdb_and_matches_the_pinned_parity(unpacked, manifest):
    pytest.importorskip("pandas")
    from adapters import _cell_value, _sanitize_rows
    from open_fdd.parity import Policy, compare, generate, reference
    from stress import BASELINE

    con = _offline_duckdb(unpacked)
    ds = generate(0, 4, 3, "basic")
    rows_by_table = {"history": ds.history, "weather": ds.weather, "sensor_history": ds.sensor_history,
                     "utility_interval": ds.utility_interval, "utility_monthly": ds.utility_monthly}
    for table, spec in manifest["input_tables"].items():
        rows = rows_by_table.get(table) or []
        if rows:
            names = ", ".join(f'"{c["name"]}"' for c in spec)
            marks = ", ".join("?" * len(spec))
            con.executemany(f"INSERT INTO {table} ({names}) VALUES ({marks})",
                            [tuple(_cell_value(row, c) for c in spec) for row in rows])
    assert con.execute("SELECT count(*) FROM history").fetchone()[0] == len(ds.history)

    results, errors = {}, {}
    for r in manifest["rules"]:
        sql = (unpacked / r["dialects"]["duckdb"]["file"]).read_text(encoding="utf-8")
        try:
            cur = con.execute(sql)
            results[r["rule_id"]] = _sanitize_rows([d[0] for d in cur.description], cur.fetchall())
        except Exception as exc:  # collect every failure, not just the first
            errors[r["rule_id"]] = str(exc)
    assert errors == {}
    assert len(results) == manifest["rule_count"]

    pinned = next(d for d in json.loads(BASELINE.read_text(encoding="utf-8"))["datasets"]
                  if (d["equips"], d["days"], d["profile"]) == (4, 3, "basic"))
    verdict = compare(results, reference(ds), Policy.default("basic", stress=True))
    assert {k: verdict.to_dict()[k] for k in pinned["verdict"]} == pinned["verdict"], verdict.summary()
    assert verdict.ok
