#!/usr/bin/env python3
"""Print an NF site's Haystack model and live values over the LAN and/or the portal, and compare.

Everything is found by Haystack tags in NF's model layer, nothing by name:

  sites    model records of kind SITE
  devices  model records of kind DEVICE           (deviceRef target)
  equips   model records of kind EQUIPMENT        (equipRef target)
  points   merged-layer points with the `point` marker and that siteRef, grouped under their
           equipRef or weatherStationRef

So the same script works on any NF whose points are tagged; to support a new building, tag it in
NF, don't edit this file. Two network paths reach the same NF API:

  lan     straight to the NF console port or your TLS front door (NF_LAN_URL)
  portal  the Normal Online hostname (NFURL); NF dials out, no inbound ports

Settings (environment, or an env file passed with --env; never commit it):

  NF_LAN_URL=https://<nf-host>   NF_CA_FILE=<self-signed LAN cert>   NFURL=https://<id>.normal-online.net
  NF_CLIENT_ID=...               NF_CLIENT_SECRET=...                 (console: Settings > API Keys)

Examples:

  python3 scripts/nf/tools/nf_portal_sensors.py --env ~/.secrets/nf_api.env
  python3 scripts/nf/tools/nf_portal_sensors.py lan --tags discharge,air,temp
  python3 scripts/nf/tools/nf_portal_sensors.py portal --tags temp,sensor

--tags is a Haystack-style marker filter: every listed marker must be present. With both paths
the script compares the values (same uuid and sample time must carry the same number); exit 1 on
a mismatch or an unreachable path.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error

import nf_common as nf


def tagged_points(base: str, token: str, site_id: str, tags: list[str]) -> list[dict]:
    """Points on a site carrying `point` plus every marker in tags (merged layer)."""
    clauses = [nf.field("siteRef", site_id), nf.field("markers", "point")]
    clauses += [nf.field("markers", t) for t in tags]
    return nf.query(base, token, "default", *clauses)


def fmt_value(point: dict) -> str:
    attrs = point.get("attrs") or {}
    value = nf.latest_number(point)
    if value is None:
        return "-"
    if attrs.get("kind") == "Bool":
        return "on" if value else "off"
    return f"{value:.2f} {attrs.get('unit', '')}".rstrip()


def print_site(site: dict, site_id: str, kinds: dict[str, list[dict]], points: list[dict]) -> None:
    def on_site(rec: dict) -> bool:
        return (rec.get("attrs") or {}).get("siteRef") == site_id

    print(f"   site  {site.get('name')}  [{site_id}]")
    for dev in filter(on_site, kinds.get("DEVICE", [])):
        a = dev.get("attrs") or {}
        print(f"   device  {a.get('id')}  {a.get('dis', dev.get('name'))}  [{' '.join(nf.markers(dev))}]")

    # Group points under their equip or weather station ref.
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in points:
        a = p.get("attrs") or {}
        if a.get("equipRef"):
            key = ("equip", a["equipRef"])
        elif a.get("weatherStationRef"):
            key = ("weatherStation", a["weatherStationRef"])
        else:
            key = ("site", site_id)
        groups.setdefault(key, []).append(p)

    equips = {(e.get("attrs") or {}).get("id"): e for e in filter(on_site, kinds.get("EQUIPMENT", []))}
    for (kind, ref), members in sorted(groups.items()):
        equip = equips.get(ref) if kind == "equip" else None
        tag_note = f"  [{' '.join(nf.markers(equip))}]" if equip else ""
        print(f"   {kind}  {ref}{tag_note}")
        rows = []
        for p in members:
            a = p.get("attrs") or {}
            tags = " ".join(m for m in nf.markers(p) if m not in nf.GENERIC_MARKERS)
            ts = (p.get("latestValue") or {}).get("ts", "")
            rows.append((tags, fmt_value(p), a.get("dis") or p.get("name", ""), ts[:19]))
        width = max(len(r[0]) for r in rows)
        for tags, value, dis, ts in sorted(rows):
            print(f"      {tags:{width}}  {value:>12}  {dis}  @ {ts}")


def print_model(label: str, base: str, client_id: str, client_secret: str,
                tags: list[str]) -> dict[str, dict] | None:
    """Print the tag tree for one base URL. Returns {uuid: latestValue} or None on failure."""
    print(f"\n== {label}: {base}")
    started = time.monotonic()
    try:
        token = nf.bearer_token(base, client_id, client_secret)
        model = nf.query(base, token, "model")
        kinds: dict[str, list[dict]] = {}
        for rec in model:
            kinds.setdefault(rec.get("pointType", ""), []).append(rec)
        sites = kinds.get("SITE", [])
        if not sites:
            print("   no SITE records in the model layer: tag the site in NF first", file=sys.stderr)
            return None
        seen: dict[str, dict] = {}
        for site in sites:
            site_id = (site.get("attrs") or {}).get("id") or site.get("name")
            points = tagged_points(base, token, site_id, tags)
            print_site(site, site_id, kinds, points)
            seen.update({p["uuid"]: p.get("latestValue") or {} for p in points})
    except urllib.error.URLError as exc:
        # Connection refused / no route, e.g. the LAN path while off site.
        print(f"   unreachable: {exc.reason}", file=sys.stderr)
        return None
    except SystemExit as exc:
        print(f"   {exc}", file=sys.stderr)
        return None
    elapsed_ms = (time.monotonic() - started) * 1000
    print(f"   {len(seen)} tagged points, model + queries {elapsed_ms:.0f} ms")
    return seen


def _num(sample: dict) -> object:
    return sample.get("double", sample.get("real"))


def compare(results: dict[str, dict[str, dict]]) -> bool:
    """Same uuid, same sample timestamp: the values must match across paths."""
    (a_name, a), (b_name, b) = results.items()
    common = a.keys() & b.keys()
    same_ts = [u for u in common if a[u].get("ts") and a[u].get("ts") == b[u].get("ts")]
    mismatched = [u for u in same_ts if _num(a[u]) != _num(b[u])]
    print(f"\n== compare {a_name} vs {b_name}: {len(common)} points on both, "
          f"{len(same_ts)} with the same sample time, {len(mismatched)} mismatched")
    if len(common) != len(a) or len(common) != len(b):
        print(f"   point sets differ: {len(a)} vs {len(b)}", file=sys.stderr)
        return False
    return not mismatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", metavar="lan|portal",
                        help="network paths to use (default: every path whose URL is set)")
    parser.add_argument("--tags", default="", help="comma list of required markers, e.g. temp,sensor")
    nf.add_env_arg(parser)
    args = parser.parse_args(argv)
    unknown = [p for p in args.paths if p not in nf.PATHS]
    if unknown:
        parser.error(f"unknown path {unknown}; use: {', '.join(nf.PATHS)}")
    nf.console_utf8()

    try:
        client_id, client_secret = nf.load_settings(args.env)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    paths = args.paths or [p for p, var in nf.PATHS.items() if os.environ.get(var)]
    if not paths:
        print(f"set {' and/or '.join(nf.PATHS.values())} (environment or --env FILE)", file=sys.stderr)
        return 1

    tags = nf.split_csv(args.tags)
    results: dict[str, dict[str, dict]] = {}
    ok = True
    for path in paths:
        seen = print_model(path.upper(), nf.base_url(path), client_id, client_secret, tags)
        if seen is None:
            ok = False
        else:
            results[path] = seen
    if len(results) == 2:
        ok = compare(results) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
