"""#1806: the pinnable rules bundle is complete, reproducible and runs every rule offline on in-memory DuckDB.

Set ``RULES_BUNDLE_ZIP`` to test a prebuilt zip (the tag workflow does); otherwise a fresh bundle is built.
"""
import hashlib
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
    roles = {r["role"]: r for r in json.loads((ROOT / "roles" / "openfdd-roles.json").read_text(encoding="utf-8"))["roles"]}
    units = json.loads((ROOT / "roles" / "openfdd-roles.json").read_text(encoding="utf-8"))["units"]
    catalog = {r["id"]: r for r in json.loads((ROOT / "nf-app" / "static" / "fdd-catalog.json").read_text(encoding="utf-8"))["rules"]}
    for r in manifest["rules"]:
        assert r["title"] and r["confirm_min"] * 60 == catalog[r["rule_id"]]["confirm_seconds"]   # existing default
        for i in r["inputs"]:
            ref = roles[i["role"]]                                    # every input is a roles-file role, exactly
            assert i["legacy_key"] == ref["role"] or i["legacy_key"] in (ref.get("legacy_keys") or []), (r["rule_id"], i)
            assert i["unit"] == (ref["unit"].split(":", 1)[1] if ref["unit"] else None)   # QUDT local name
            assert i["value_type"] == ref["value_type"]
            assert i["unit_display"] == (units[ref["unit"]]["haystack"] if ref["unit"] else None)
            assert i["unit"] is None or i["unit"] == units[ref["unit"]]["wire"]
        for dialect in ("postgresql", "timescaledb", "duckdb"):
            assert (unpacked / r["dialects"][dialect]["file"]).is_file()
        assert "{{" not in (unpacked / r["dialects"]["duckdb"]["file"]).read_text(encoding="utf-8")
    other = manifest["confirm_min"]["rules_with_other_default"]
    assert {r["rule_id"] for r in manifest["rules"] if r["confirm_min"] != 15} == set(other)


def test_per_file_sha256_matches_every_entry(manifest, unpacked):
    listed = manifest["files"]
    on_disk = sorted(p.relative_to(unpacked).as_posix() for p in unpacked.rglob("*") if p.is_file())
    assert sorted(listed) == [n for n in on_disk if n != "rules-manifest.json"]
    for name, meta in listed.items():
        data = (unpacked / name).read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (meta["sha256"], meta["bytes"]), name


def test_roles_file_ships_unchanged_with_the_recorded_version(manifest, unpacked):
    shipped = unpacked / "roles" / "openfdd-roles.json"
    repo = (ROOT / "roles" / "openfdd-roles.json").read_bytes()
    assert manifest["roles_vocabulary"]["file"] == "roles/openfdd-roles.json"
    assert shipped.read_bytes() == repo
    assert manifest["files"]["roles/openfdd-roles.json"]["sha256"] == hashlib.sha256(repo).hexdigest()
    assert json.loads(repo.decode("utf-8"))["version"] == manifest["roles_vocabulary"]["version"]


def test_templates_rerender_to_the_shipped_sql(manifest, unpacked):
    spec_r = importlib.util.spec_from_file_location("bundle_render_rule", unpacked / "templates" / "sql" / "fdd" / "render_rule.py")
    rr = importlib.util.module_from_spec(spec_r)
    spec_r.loader.exec_module(rr)
    for r in manifest["rules"]:
        sql = rr.render(r["rule_id"], 300)
        shipped = (unpacked / r["dialects"]["postgresql"]["file"]).read_text(encoding="utf-8")
        assert sql.replace("\r\n", "\n").rstrip("\n") + "\n" == shipped, r["rule_id"]


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
