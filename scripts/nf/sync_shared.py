#!/usr/bin/env python3
"""Copy the code both editions share from shared/ into the Full (nf-app/) and Lite (lite/) app trees.

The two NF apps are served from their own folders (the installer reads each app.json file list, the type checks and
tests read each tree), so a shared file still has to exist inside both. Its ONE source lives under shared/; this script
writes the copies, each with a one-line "generated copy" banner, and ``--check`` fails (exit 1, for CI and pytest) when
a copy is missing, hand-edited or stale. Edit shared/..., run this script, commit both.

    shared/paging.js                        -> {nf-app,lite}/hooks/lib/paging.js, {nf-app,lite}/static/paging.js
    shared/hooks/settings.js                -> {nf-app,lite}/hooks/lib/settings.js
    shared/hooks/site-timezone.js           -> nf-app/hooks/lib/site-timezone.js   (the fdd / analytics hooks' site time zone, same order as the UI)
    shared/role-limits.js                   -> nf-app/hooks/lib/role-limits.js, nf-app/static/role-limits.js   (sweep role-limit overrides, #1589; Full only)
    shared/hooks/open_meteo_weather.js      -> nf-app/hooks/weather.js, lite/hooks/open_meteo_weather.js   (edition constant substituted: 'full' / 'lite')
    shared/static/<file>                    -> {nf-app,lite}/static/<file>
        the dashboard shell: app-core.js (top bar, equip pickers, tab router, Overview, Charts, Points, BACnet Server,
        Model & RDF, live loop), charts.js (chart catalog, range / history helpers), theme.js (light / dark + ECharts
        themes), chart-page.js (chart.html), tree.js (tree.html), base.css (CSS base); and nf.js, model.js,
        theme-init.js, tree.css, version.js
    shared/types/shapes.d.ts                -> {nf-app,lite}/types/shapes.d.ts

Edition-specific files stay in their own tree: app.js (Lite: starts the shell; Full: registers the FDD / RCx / Export
tabs, units toggle and Run FDD through the ofddTabs / ofddWire registries of app-core.js), index.html / chart.html /
tree.html (script lists differ: Full loads the ES-module ECharts, Lite the UMD build), style.css (edition rules on top
of base.css), and everything only Full has (fdd*.js, rcx*.js, energy.js, export.js, sparql.js, units.js, ...).

    python scripts/nf/sync_shared.py            # write the copies
    python scripts/nf/sync_shared.py --check    # exit 1 when a copy is missing or differs from its source
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOTH = ("nf-app", "lite")

# source (relative to the repo root) -> destinations (relative to the repo root)
SHARED: dict[str, list[str]] = {
    "shared/paging.js": [f"{app}/{sub}/paging.js" for app in BOTH for sub in ("hooks/lib", "static")],
    "shared/hooks/settings.js": [f"{app}/hooks/lib/settings.js" for app in BOTH],
    "shared/hooks/site-timezone.js": ["nf-app/hooks/lib/site-timezone.js"],
    "shared/role-limits.js": ["nf-app/hooks/lib/role-limits.js", "nf-app/static/role-limits.js"],
    "shared/rule-tuning.js": ["nf-app/hooks/lib/rule-tuning.js", "nf-app/static/rule-tuning.js"],
    "shared/hooks/open_meteo_weather.js": ["nf-app/hooks/weather.js", "lite/hooks/open_meteo_weather.js"],
    "shared/types/shapes.d.ts": [f"{app}/types/shapes.d.ts" for app in BOTH],
}
for _name in ("nf.js", "model.js", "theme-init.js", "tree.css", "version.js",
              "app-core.js", "charts.js", "theme.js", "chart-page.js", "tree.js", "base.css"):
    SHARED[f"shared/static/{_name}"] = [f"{app}/static/{_name}" for app in BOTH]


# per-destination text substitutions (the edition constant of the shared weather hook)
SUBST: dict[str, tuple[str, str]] = {
    "nf-app/hooks/weather.js": ("'__OFDD_EDITION__'", "'full'"),
    "lite/hooks/open_meteo_weather.js": ("'__OFDD_EDITION__'", "'lite'"),
}


def banner(source: str, dest: str) -> str:
    text = f"GENERATED COPY of {source} by scripts/nf/sync_shared.py: edit the source, then re-run the script."
    return f"/* {text} */" if dest.endswith(".css") else f"// {text}"


def expected(source: str, dest: str) -> str:
    """The destination's text (LF line endings): banner line + the source."""
    body = (ROOT / source).read_bytes().decode("utf-8").replace("\r\n", "\n")
    if dest in SUBST:
        old, new = SUBST[dest]
        assert old in body, f"{source} lacks {old}"
        body = body.replace(old, new)
    return banner(source, dest) + "\n" + body


def pairs() -> list[tuple[str, str]]:
    return [(src, dst) for src, dests in SHARED.items() for dst in dests]


def stale() -> list[str]:
    """Destinations that are missing or whose content (line endings ignored) differs from their source."""
    out = []
    for src, dst in pairs():
        path = ROOT / dst
        have = path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.is_file() else None
        if have != expected(src, dst):
            out.append(dst)
    return out


def write_all() -> list[str]:
    wrote = []
    for src, dst in pairs():
        path = ROOT / dst
        text = expected(src, dst)
        have = path.read_bytes().decode("utf-8") if path.is_file() else None
        crlf = have is not None and "\r\n" in have          # keep a CRLF checkout CRLF (git normalizes either way)
        out = text.replace("\n", "\r\n") if crlf else text
        if have != out:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(out.encode("utf-8"))
            wrote.append(dst)
    return wrote


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if any copy is missing or stale")
    args = ap.parse_args(argv)
    for src, _ in pairs():
        if not (ROOT / src).is_file():
            print(f"missing shared source {src}", file=sys.stderr)
            return 1
    if args.check:
        bad = stale()
        if bad:
            print("shared copies are stale (run python scripts/nf/sync_shared.py): " + ", ".join(bad), file=sys.stderr)
            return 1
        print(f"shared copies are up to date ({len(pairs())} files from {len(SHARED)} sources)")
        return 0
    wrote = write_all()
    for dst in wrote:
        print(f"wrote {dst}")
    print(f"{len(wrote)} file(s) written, {len(pairs()) - len(wrote)} already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
