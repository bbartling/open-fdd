"""#1567: the NF-native install tree (git URL / zip) is built from the same manifest nf_app_sync pushes."""
import importlib.util
import json
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


def test_tree_matches_the_push_manifest(tmp_path):
    sync = dist._load_sync()
    for edition, path in dist.EDITIONS.items():
        m = sync.manifest(path)
        tree, files = dist.build(edition, tmp_path)
        assert not dist.problems(edition, tree, files)
        for nf_path, rel in m["files"].items():          # byte-for-byte what nf_app_sync uploads
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


def test_zip_is_reproducible_and_rooted(tmp_path):
    tree, files = dist.build("lite", tmp_path / "a")
    z1 = dist.zip_tree(tree, files, tmp_path / "one.zip")
    z2 = dist.zip_tree(tree, files, tmp_path / "two.zip")
    assert z1.read_bytes() == z2.read_bytes()
    with zipfile.ZipFile(z1) as z:
        names = z.namelist()
    assert "app.json" in names and "hooks-update/open-meteo-weather.json" in names and not any(n.startswith("open-fdd") for n in names)
