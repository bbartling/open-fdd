#!/usr/bin/env python3
"""Pin the Open-FDD SQL catalog as a versioned rules zip.

The archive contains:

* every file under ``sql/`` (the full catalog, not a sensor-sweep subset);
* ``pack.json``, the PostgreSQL pack rendered for every registry rule;
* ``manifest.json``, whose only user tuner is ``confirm_min`` (default 15 minutes).

Other tuners are baked at their shipped defaults. Rules that do not accept
``confirm_min`` keep their catalog defaults. The version is the app ``VERSION`` file.

Usage:
  python scripts/nf/build_rules_bundle.py
  python scripts/nf/build_rules_bundle.py dist/open-fdd-rules.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_ROOT = ROOT / "sql"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
POLL_SECONDS = 300
CONFIRM_MIN = 15
USER_TUNERS = [
    {"key": "confirm_min", "default": CONFIRM_MIN, "unit": "min", "min": 0, "max": 60},
]


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def default_dest() -> Path:
    return ROOT / "dist" / f"open-fdd-rules-{version()}.zip"


def sql_files() -> list[Path]:
    """Every file under sql/, in stable order. Skips bytecode caches."""
    out = []
    for path in SQL_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        out.append(path)
    return sorted(out, key=lambda p: p.relative_to(ROOT).as_posix())


def _render():
    sql_dir = str(SQL_ROOT / "fdd")
    if sql_dir not in sys.path:
        sys.path.insert(0, sql_dir)
    import render_rule  # noqa: WPS433 (path import of the catalog renderer)

    return render_rule.render


def _registry_rules() -> list[dict]:
    import yaml

    registry = yaml.safe_load((SQL_ROOT / "fdd" / "registry.yaml").read_text(encoding="utf-8"))
    rules = registry["rules"]
    ids = [rule["rule_id"] for rule in rules]
    if len(ids) != len(set(ids)):
        raise SystemExit("registry.yaml has duplicate rule ids")
    return rules


def _tuning_by_id() -> dict[str, dict]:
    catalog = json.loads((SQL_ROOT / "fdd" / "tuning_catalog.json").read_text(encoding="utf-8"))
    return {rule["rule_id"]: rule for rule in catalog["rules"]}


def render_pack() -> dict:
    """Rendered PostgreSQL pack. confirm_min is 15 on every rule that accepts it."""
    render = _render()
    tuning = _tuning_by_id()
    rules = {}
    for rule in _registry_rules():
        rule_id = rule["rule_id"]
        spec = tuning.get(rule_id)
        if spec is None:
            raise SystemExit(f"{rule_id} is in registry.yaml but not tuning_catalog.json")
        accepts = "confirm_min" in spec.get("parameters", {})
        overrides = {"confirm_min": CONFIRM_MIN} if accepts else None
        sql = render(rule_id, POLL_SECONDS, overrides)
        if "{{" in sql:
            raise SystemExit(f"{rule_id} still has an unresolved placeholder")
        rules[rule_id] = {
            "sql": sql,
            "sql_file": rule["sql_file"],
            "output_columns": list(rule["output_columns"]),
            "confirm_min": CONFIRM_MIN if accepts else None,
        }
    return {
        "dialect": "postgres",
        "poll_seconds": POLL_SECONDS,
        "confirm_min": CONFIRM_MIN,
        "rule_count": len(rules),
        "rules": rules,
    }


def _dumps(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_for(files: dict[str, bytes], pack: dict) -> dict:
    listed = {
        name: {"sha256": _sha256(data), "bytes": len(data)}
        for name, data in sorted(files.items())
    }
    return {
        "name": "open-fdd-rules",
        "version": version(),
        "rule_count": pack["rule_count"],
        "poll_seconds": POLL_SECONDS,
        "pack": "pack.json",
        "user_tuners": USER_TUNERS,
        "files": listed,
    }


def bundle_bytes(pack: dict | None = None) -> dict[str, bytes]:
    """Archive members except manifest.json (the manifest hashes these bytes)."""
    files = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in sql_files()}
    rendered = pack if pack is not None else render_pack()
    files["pack.json"] = _dumps(rendered)
    return files


def build_bundle(dest: Path | None = None) -> Path:
    dest = Path(dest) if dest is not None else default_dest()
    pack = render_pack()
    files = bundle_bytes(pack)
    manifest = manifest_for(files, pack)
    if manifest["user_tuners"] != USER_TUNERS:
        raise SystemExit("manifest user tuners drifted from confirm_min default 15")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
        info = zipfile.ZipInfo("manifest.json", FIXED_ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, _dumps(manifest))
    return dest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", nargs="?", type=Path, help="zip path (default dist/open-fdd-rules-<version>.zip)")
    args = parser.parse_args(argv)
    print(build_bundle(args.dest))


if __name__ == "__main__":
    main()
