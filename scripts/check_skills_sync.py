#!/usr/bin/env python3
"""Check canonical skill discovery pointers and README catalog badges; --write repairs generated text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def expected_files(root: Path) -> dict[Path, str]:
    files = {}
    for source in sorted((root / "openfdd_agent_spec/skills").glob("*.md")):
        text = source.read_text(encoding="utf-8")
        name = re.search(r"^name: (.+)$", text, re.M).group(1)
        description = re.search(r"^description: (.+)$", text, re.M).group(1)
        if name != source.stem:
            raise ValueError(f"skill name disagrees with filename: {source}")
        pointer = (f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n\n"
                   f"Follow `openfdd_agent_spec/skills/{name}.md` (read `AGENTS.md` first). "
                   "Edit that file, not this pointer.\n")
        for directory in (".agents", ".claude"):
            files[root / directory / "skills" / name / "SKILL.md"] = pointer
    return files


def check(root: Path, write: bool = False) -> list[str]:
    from open_fdd.rules.cookbook_catalog import RULES_BY_ID

    errors = []
    expected = expected_files(root)
    for path, text in expected.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            else:
                errors.append(f"stale/missing pointer: {path.relative_to(root)}")
    for directory in (".agents", ".claude"):
        for path in (root / directory / "skills").glob("*/SKILL.md"):
            if path not in expected:
                errors.append(f"pointer without canonical skill: {path.relative_to(root)}")

    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    if len(re.findall(r"https://x\.ai/bot/[A-Za-z0-9]+", readme)) != 1:
        errors.append("README needs one shared bot/template link; badges should link to its section")
    count = len(json.loads((root / "nf-app/static/fdd-catalog.json").read_text(encoding="utf-8"))["rules"])
    pandas_count = len(RULES_BY_ID)
    updated, url_count = re.subn(r"FDD%20Rule%20Cookbook-\d+%20SQL%20%2B%20\d+%20Pandas",
                               f"FDD%20Rule%20Cookbook-{count}%20SQL%20%2B%20{pandas_count}%20Pandas", readme)
    updated, alt_count = re.subn(r"FDD Rule Cookbook — \d+ SQL \+ \d+ pandas",
                               f"FDD Rule Cookbook — {count} SQL + {pandas_count} pandas", updated)
    if (url_count, alt_count) != (1, 1):
        errors.append("README must contain one cookbook badge and its count-bearing alt text")
    if updated != readme:
        if write:
            readme_path.write_text(updated, encoding="utf-8")
        else:
            errors.append("README cookbook counts drifted; run python scripts/check_skills_sync.py --write")
    for source in (root / "openfdd_agent_spec/skills").glob("*.md"):
        if f"openfdd_agent_spec/skills/{source.name}" not in readme:
            errors.append(f"README missing canonical skill link: {source.name}")
    # PyPI's badge reads its version from the index, not the separately versioned NF app.
    if "https://img.shields.io/pypi/v/open-fdd?" not in readme:
        errors.append("README needs the live PyPI version badge")
    app_version = json.loads((root / "nf-app/package.json").read_text(encoding="utf-8"))["version"]
    if app_version != (root / "VERSION").read_text(encoding="utf-8").strip():
        errors.append("NF package version differs from VERSION")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    errors = check(ROOT, args.write)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("skill pointers, README catalog counts and version badges checked")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
