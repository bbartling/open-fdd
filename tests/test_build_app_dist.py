"""#1567: the NF-native install tree (git URL / zip) is built from the same manifest nf_app_sync pushes."""
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_app_dist", ROOT / "scripts" / "nf" / "build_app_dist.py")
dist = importlib.util.module_from_spec(spec)
sys.modules["build_app_dist"] = dist
spec.loader.exec_module(dist)


def test_check_passes_for_both_editions():
    assert dist.main(["--check"]) == 0


# The engine recipes rewrite these after the push-manifest copy.
STAMPED = {"/package.json", "/static/index.html", "/static/chart.html", "/static/tree.html", "/static/engine-build.json"}


def test_tree_matches_the_push_manifest(tmp_path):
    sync = dist._load_sync()
    for edition, path in dist.EDITIONS.items():
        m = sync.manifest(path)
        recipe = "duckdb" if edition == "full" else None
        tree, files = dist.build(edition, tmp_path, recipe)
        assert not dist.problems(edition, tree, files, recipe)
        for nf_path, rel in m["files"].items():          # byte-for-byte what nf_app_sync uploads, except the recipe stamp
            if edition == "full" and nf_path in STAMPED:
                continue
            assert (tree / nf_path.lstrip("/")).read_bytes() == sync.deploy_bytes(m, rel), nf_path
        native = json.loads((tree / "app.json").read_text(encoding="utf-8"))
        assert native["id"] == m["application"]["id"] and "hooks" not in native and "files" not in native
        assert {o["name"] for o in native["options"]} >= {"timezone", "weather", "exporters", "latitude", "longitude"}
        assert sorted(p.stem for p in (tree / "hooks-update").glob("*.json")) == sorted(h["id"] for h in m["hooks"])
        if edition == "full":
            assert "timescale" in {o["name"] for o in native["options"]}
        else:
            assert "timescale" not in {o["name"] for o in native["options"]}
            assert json.loads((tree / "package.json").read_text())["private"] is True   # NF runs npm install


def test_each_engine_recipe_stamps_its_badge(tmp_path):
    for recipe, label, dep in (
        ("duckdb", "DuckDB build", "@duckdb/node-api"),
        ("timescale", "Timescale build", "pg"),
    ):
        tree, files = dist.build("full", tmp_path, recipe)
        assert not dist.problems("full", tree, files, recipe)
        for name in ("index.html", "chart.html", "tree.html"):
            html = (tree / "static" / name).read_text(encoding="utf-8")
            badge = re.search(r'id="engineBuild"[^>]*>([^<]*)</span>', html)
            assert badge and badge.group(1) == label, name
            assert not re.search(r"\d", badge.group(1))
            assert f'name="ofdd-engine-build" content="{recipe}"' in html
        rec = json.loads((tree / "static" / "engine-build.json").read_text(encoding="utf-8"))
        assert rec["id"] == recipe and rec["label"] == label and rec["libraryVersion"]
        version = json.loads((tree / "static" / "version.json").read_text(encoding="utf-8"))
        assert version["engineLabel"] == label and version["engineLibraryVersion"] == rec["libraryVersion"]
        assert version["engineBuild"] == recipe
        deps = json.loads((tree / "package.json").read_text(encoding="utf-8"))["dependencies"]
        assert set(deps) == {dep, "oxigraph"}
        assert "sql.js" not in deps and "@electric-sql/pglite" not in deps


def test_zip_is_reproducible_and_rooted(tmp_path):
    tree, files = dist.build("lite", tmp_path / "a")
    z1 = dist.zip_tree(tree, files, tmp_path / "one.zip")
    z2 = dist.zip_tree(tree, files, tmp_path / "two.zip")
    assert z1.read_bytes() == z2.read_bytes()
    with zipfile.ZipFile(z1) as z:
        names = z.namelist()
    assert "app.json" in names and "hooks-update/open-meteo-weather.json" in names and not any(n.startswith("open-fdd") for n in names)
