#!/usr/bin/env python3
"""Build the NF-native install tree of an edition: what NF's own "git URL" install and an IT hand-off zip need (#1567).

NF's git install clones a repository into the app's sandbox and reads, from the ROOT of that repository: ``app.json`` (the
CreateApplication request: id, name, runtime, auth, options), ``hooks-update/*.json`` (one UpdateHook body per hook),
``static/``, ``package.json`` and the hook sources the entry points name. This repo keeps its two editions in ``nf-app/``
and ``lite/`` with a manifest (``app.json``: application + file map + hooks) for ``nf_app_sync.py``, so a clone of the repo
root is not an app. This script turns a manifest into the tree NF expects, from the same file map and hook definitions that
``nf_app_sync.py`` pushes (so the two install paths cannot disagree):

    python scripts/nf/build_app_dist.py --edition lite --out build/dist            # build/dist/open-fdd-lite/
    python scripts/nf/build_app_dist.py --edition both --out build/dist --zip      # + open-fdd-<edition>-<version>.zip each
    python scripts/nf/build_app_dist.py --check                                    # build both in a temp dir and verify (CI, pytest)

Publish a tree as the root of its own git repository (or a branch of a mirror) for method A, or hand the zip to IT.
CI attaches the zips to each GitHub release (.github/workflows/nf-app-release.yml).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITIONS = {"full": ROOT / "nf-app" / "app.json", "lite": ROOT / "lite" / "app.json"}
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
# The two runtime builds. The source tree is the DuckDB build; the Timescale recipe rewrites the badge.
RECIPES = ("duckdb", "timescale")
BADGES = {"duckdb": "DuckDB build", "timescale": "Timescale build"}
PINS = {"duckdb": ("@duckdb/node-api", "2.0.1-r.1"), "timescale": ("pg", "8.23.1")}
RECIPE_DEPS = {"duckdb": {"@duckdb/node-api": "2.0.1-r.1"}, "timescale": {"pg": "8.23.1"}}
HTML_BADGES = ("static/index.html", "static/chart.html", "static/tree.html")


def _load_sync():
    spec = importlib.util.spec_from_file_location("nf_app_sync", ROOT / "scripts" / "nf" / "hooks" / "nf_app_sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("nf_app_sync", mod)
    spec.loader.exec_module(mod)
    return mod


def _opt(name: str, description: str, default: str = "") -> dict:
    return {"name": name, "description": description, "optionType": "TYPE_STRING", "defaultValue": {"string": default}}


# The settings the NF console's Configure form shows after a git install. All strings (NF stores app options as scalars
# and the hooks convert them: shared/hooks/settings.js). Blank = not set.
COMMON_OPTIONS = [
    _opt("timezone", "IANA time zone of the site (e.g. America/Chicago) when the modeled site has no tz"),
    _opt("weather", "true / false: false turns the Open-Meteo weather fetch off (no outbound request)", "true"),
    _opt("exporters", "Weather outputs besides the hook variables: bacnet-av (default when NF's BACnet server is present), a comma list, or none"),
    _opt("latitude", "Site latitude override (otherwise NF Sites, then the modeled site)"),
    _opt("longitude", "Site longitude override"),
    _opt("site", "NF site id, only needed when several sites have coordinates"),
]
FULL_OPTIONS = [
    _opt("engine", "FDD engine: auto | duckdb | timescale. auto uses DuckDB unless Timescale is configured. sqlite and pglite were removed.", "auto"),
    _opt("windowHours", "Trailing window per FDD run, hours", "24"),
    _opt("timescale", 'Timescale connection as JSON {"host","port","database","user","password"} or a postgres:// URL (a secret)'),
]


def options_for(edition: str, recipe: str | None = None) -> list[dict]:
    if edition != "full":
        return list(COMMON_OPTIONS)
    engine_default = "timescale" if recipe == "timescale" else "auto"
    full = [dict(o) for o in FULL_OPTIONS]
    full[0] = _opt(full[0]["name"], full[0]["description"], engine_default)
    return COMMON_OPTIONS + full


def engine_record(recipe: str) -> dict:
    lib, ver = PINS[recipe]
    return {"id": recipe, "label": BADGES[recipe], "library": lib, "libraryVersion": ver}


def stamp_html(text: str, recipe: str) -> str:
    lib, ver = PINS[recipe]
    label = BADGES[recipe]
    text = re.sub(r'(<meta name="ofdd-engine-build" content=")[^"]+(")', rf"\g<1>{recipe}\g<2>", text)
    text = re.sub(r'(<meta name="ofdd-engine-library" content=")[^"]+(")', rf"\g<1>{lib}\g<2>", text)
    text = re.sub(r'(<meta name="ofdd-engine-library-version" content=")[^"]+(")', rf"\g<1>{ver}\g<2>", text)
    text = re.sub(r'(id="engineBuild" data-ofdd-engine=")[^"]+(")', rf"\g<1>{recipe}\g<2>", text)
    text = re.sub(r'(id="engineBuild" data-ofdd-engine="[^"]+">)[^<]*(</span>)', rf"\g<1>{label}\g<2>", text)
    return text


def apply_recipe(tree: Path, recipe: str) -> None:
    """Stamp the engine badge, the build file, version.json and the install dependencies."""
    rec = engine_record(recipe)
    (tree / "static" / "engine-build.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    for rel in HTML_BADGES:
        path = tree / rel
        if path.is_file():
            path.write_text(stamp_html(path.read_text(encoding="utf-8"), recipe), encoding="utf-8")
    vpath = tree / "static" / "version.json"
    if vpath.is_file():
        version = json.loads(vpath.read_text(encoding="utf-8"))
        version.update(engineBuild=recipe, engineLabel=rec["label"], engineLibrary=rec["library"], engineLibraryVersion=rec["libraryVersion"])
        vpath.write_text(json.dumps(version) + "\n", encoding="utf-8")
    pkg = tree / "package.json"
    if pkg.is_file():
        meta = json.loads(pkg.read_text(encoding="utf-8"))
        meta["dependencies"] = dict(RECIPE_DEPS[recipe])
        meta.pop("optionalDependencies", None)
        meta.pop("devDependencies", None)
        pkg.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    native = json.loads((tree / "app.json").read_text(encoding="utf-8"))
    for opt in native.get("options", []):
        if opt.get("name") == "engine":
            opt["defaultValue"] = {"string": "timescale" if recipe == "timescale" else "auto"}
    (tree / "app.json").write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")


def build(edition: str, out: Path, recipe: str | None = None) -> tuple[Path, list[str]]:
    """Write the install tree of `edition` to out/<application id>/ and return (tree dir, relative file list).

    Full has two recipes. `duckdb` (the default) is the single-site build; `timescale` is the Timescale build.
    The Timescale tree is `out/<app-id>-timescale` so both can sit side by side. The app id inside stays `open-fdd`.
    """
    sync = _load_sync()
    m = sync.manifest(EDITIONS[edition])
    app = dict(m["application"])
    app_id = app["id"]
    if app.get("name") and sync.app_slug(app["name"]) != app_id:
        raise SystemExit(f"{edition}: manifest id {app_id!r} != NF's id for name {app['name']!r}")
    if edition == "full":
        recipe = recipe or "duckdb"
        if recipe not in RECIPES:
            raise SystemExit(f"unknown engine recipe {recipe!r} (use duckdb or timescale)")
    else:
        recipe = None
    tree = out / (f"{app_id}-timescale" if recipe == "timescale" else app_id)
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    written: list[str] = []

    def put(rel: str, data: bytes) -> None:
        dest = tree / rel.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(rel.lstrip("/"))

    for nf_path, rel in m["files"].items():
        put(nf_path, sync.deploy_bytes(m, rel))          # same bytes nf_app_sync would upload (LF, stamped asset refs)
    info = sync.version_info(m["_dir"])
    version = info["version"]
    # app.json = the CreateApplication request (NF reads it from the repo root); no hooks / files keys, those are NF's own files
    native = {**app, "options": options_for(edition, recipe)}
    put("app.json", (json.dumps(native, indent=2) + "\n").encode())
    for h in m["hooks"]:
        put(f"hooks-update/{h['id']}.json", (json.dumps(h, indent=2) + "\n").encode())
    if "/package.json" not in m["files"]:                # NF runs npm install: give a dependency-free app a manifest
        put("package.json", (json.dumps({"name": app_id, "version": version, "private": True, "description": app.get("description", "")}, indent=2) + "\n").encode())
    put("static/version.json", (json.dumps({"version": version, "commit": info.get("commit", ""), "source": "dist"}) + "\n").encode())
    if recipe:
        apply_recipe(tree, recipe)
    return tree, sorted(written)


def zip_tree(tree: Path, files: list[str], dest: Path) -> Path:
    """A reproducible zip: the files at the archive root (so an unzipped folder is a git-installable repository root)."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            zi = zipfile.ZipInfo(rel, FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, (tree / rel).read_bytes())
    return dest


def problems(edition: str, tree: Path, files: list[str], recipe: str | None = None) -> list[str]:
    """What is wrong with a built tree (empty list = good): the checks NF's installer would trip over."""
    bad: list[str] = []
    native = json.loads((tree / "app.json").read_text(encoding="utf-8"))
    for key in ("id", "name", "runtime"):
        if not native.get(key):
            bad.append(f"app.json has no {key}")
    if "files" in native or "hooks" in native:
        bad.append("app.json must be the CreateApplication request only (no files/hooks keys)")
    if native.get("id") and native.get("name") and "-".join(re.findall(r"[a-z0-9]+", native["name"].lower())) != native["id"]:
        bad.append("app.json id is not NF's slug of its name (NF ignores the id on create)")
    hooks = sorted(p.stem for p in (tree / "hooks-update").glob("*.json"))
    manifest_hooks = sorted(h["id"] for h in json.loads(EDITIONS[edition].read_text(encoding="utf-8"))["hooks"])
    if hooks != manifest_hooks:
        bad.append(f"hooks-update has {hooks}, the manifest declares {manifest_hooks}")
    for p in sorted((tree / "hooks-update").glob("*.json")):
        h = json.loads(p.read_text(encoding="utf-8"))
        entry = h.get("entryPoint", "")
        if not (tree / entry.lstrip("/")).is_file():
            bad.append(f"hook {h.get('id')}: entryPoint {entry} is not in the tree")
    for need in ("package.json", "static/index.html"):
        if need not in files:
            bad.append(f"missing {need}")
    if edition == "full":
        recipe = recipe or "duckdb"
        html = (tree / "static" / "index.html").read_text(encoding="utf-8")
        label = BADGES[recipe]
        if label not in html:
            bad.append(f"index.html does not show {label}")
        badge = re.search(r'id="engineBuild"[^>]*>([^<]*)</span>', html)
        if not badge or badge.group(1) != label:
            bad.append(f"engine badge is {badge.group(1) if badge else 'missing'}, expected {label}")
        elif re.search(r"\d", badge.group(1)):
            bad.append("engine badge must not show a version number")
        if f'name="ofdd-engine-build" content="{recipe}"' not in html:
            bad.append(f"ofdd-engine-build meta is not {recipe}")
        rec = json.loads((tree / "static" / "engine-build.json").read_text(encoding="utf-8"))
        if rec.get("label") != label or rec.get("id") != recipe:
            bad.append(f"engine-build.json is {rec}")
        deps = json.loads((tree / "package.json").read_text(encoding="utf-8")).get("dependencies") or {}
        if deps != RECIPE_DEPS[recipe]:
            bad.append(f"package.json dependencies {deps} are not the {recipe} recipe")
        if any(name in deps for name in ("sql.js", "@electric-sql/pglite")):
            bad.append("sqlite or pglite is still an install dependency")
        version = json.loads((tree / "static" / "version.json").read_text(encoding="utf-8"))
        if version.get("engineLabel") != label or version.get("engineLibraryVersion") != PINS[recipe][1]:
            bad.append(f"version.json engine fields are { {k: version.get(k) for k in ('engineLabel', 'engineLibraryVersion')} }")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", choices=["full", "lite", "both"], default="both")
    ap.add_argument("--engine", choices=list(RECIPES), help="full edition only: duckdb or timescale (default: both recipes)")
    ap.add_argument("--out", type=Path, default=Path("build/dist"))
    ap.add_argument("--zip", action="store_true", help="also write open-fdd-<recipe>-<version>.zip next to each full tree")
    ap.add_argument("--check", action="store_true", help="build both editions and both engine recipes in a temp dir and verify; writes nothing else")
    a = ap.parse_args(argv)
    if a.edition == "lite" and a.engine:
        raise SystemExit("lite has no engine recipe")
    jobs: list[tuple[str, str | None]] = []
    if a.check or a.edition in ("lite", "both"):
        jobs.append(("lite", None))
    if a.check or a.edition in ("full", "both"):
        for recipe in ([a.engine] if a.engine else list(RECIPES)):
            jobs.append(("full", recipe))
    out = Path(tempfile.mkdtemp(prefix="ofdd-dist-")) if a.check else a.out
    rc = 0
    try:
        for ed, recipe in jobs:
            tree, files = build(ed, out, recipe)
            bad = problems(ed, tree, files, recipe)
            label = f"{ed}/{recipe}" if recipe else ed
            for b in bad:
                print(f"{label}: {b}", file=sys.stderr)
            rc |= bool(bad)
            print(f"{label}: {len(files)} files in {tree}" + (" (problems above)" if bad else ""))
            if a.zip and not a.check:
                ver = json.loads((tree / "static" / "version.json").read_text())["version"]
                name = f"{tree.name}-{ver}.zip" if not recipe else f"open-fdd-{recipe}-{ver}.zip"
                z = zip_tree(tree, files, out / name)
                print(f"{label}: {z} ({z.stat().st_size} bytes)")
    finally:
        if a.check:
            shutil.rmtree(out, ignore_errors=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
