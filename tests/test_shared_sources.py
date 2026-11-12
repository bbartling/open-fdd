"""The code Full (nf-app/) and Lite (lite/) share has ONE source under shared/; the copies must match it."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_shared", ROOT / "scripts/nf/sync_shared.py")
sync_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_shared)


def _lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_every_copy_matches_its_shared_source():
    assert sync_shared.stale() == []
    assert sync_shared.main(["--check"]) == 0


def test_a_shared_file_is_identical_in_both_app_trees():
    def norm(path: str) -> str:
        # the weather hook differs by exactly one line: the edition constant written by the generator
        return re.sub(r"\('(full|lite)'\);", "('X');", _lf(ROOT / path))

    twins = 0
    for dests in sync_shared.SHARED.values():
        full = [d for d in dests if d.startswith("nf-app/")]
        lite = [d for d in dests if d.startswith("lite/")]
        for f, l in zip(sorted(full), sorted(lite)):
            if Path(f).name == Path(l).name or f.endswith("weather.js"):
                assert norm(f) == norm(l), f"{f} differs from {l}"
                twins += 1
    assert twins >= 9
    assert "('full');" in _lf(ROOT / "nf-app/hooks/weather.js")
    assert "('lite');" in _lf(ROOT / "lite/hooks/open_meteo_weather.js")


def test_both_manifests_ship_every_shared_runtime_file():
    import json
    for app in ("nf-app", "lite"):
        files = set(json.loads((ROOT / app / "app.json").read_text(encoding="utf-8"))["files"].values())
        for dests in sync_shared.SHARED.values():
            for d in dests:
                rel = d.split("/", 1)
                if rel[0] == app and rel[1].startswith(("static/", "hooks/")):
                    assert rel[1] in files, f"{app}/app.json does not list {rel[1]}"
