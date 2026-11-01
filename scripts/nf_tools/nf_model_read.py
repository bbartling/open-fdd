#!/usr/bin/env python3
"""Read-only dump of an NF Haystack data model (sites, equipment, points).

Reads the `model` layer (and the merged `default` layer for latest values,
units and trending period). Never writes: it only calls auth/token,
point/query. Filters are ANDed; nothing is hard-coded.

  nf_model_read.py --env-file ~/.secrets/nf_acme.env --kind equip
  nf_model_read.py --env-file ~/.secrets/nf_acme.env --site acme --equip-tag vav --tags temp,sensor --format csv
  nf_model_read.py --site acme --class discharge-air-temp-sensor --format json -o dat.json
"""
from __future__ import annotations

import argparse
import sys

import nf_common as c


def select(model: list[dict], args) -> list[dict]:
    tags, excl = c.split_list(args.tags), c.split_list(args.exclude)
    eq_ids = c.equip_ids_with_tags(model, c.split_list(args.equip_tag), args.site) if args.equip_tag else None
    out = []
    for r in model:
        k = c.rec_kind(r)
        if args.kind != "all" and k != args.kind:
            continue
        if k == "point":
            if not c.point_matches(r, site=args.site, equip=args.equip, tags=tags, exclude=excl,
                                   point_class=args.point_class, equip_ids=eq_ids):
                continue
        else:
            if not c.site_matches(r, args.site):
                continue
            a = c.attrs(r)
            if args.equip and k == "equip" and a.get("id") != args.equip:
                continue
            if eq_ids is not None and k == "equip" and a.get("id") not in eq_ids:
                continue
            if args.point_class or tags:
                if not (set(tags) <= set(c.markers(r))) or (args.point_class and a.get("class") != args.point_class):
                    continue
        out.append(r)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--env-file", help="KEY=VALUE file with NFURL / NF_CLIENT_ID / NF_CLIENT_SECRET")
    p.add_argument("--via", choices=tuple(c.PATHS), default="portal")
    p.add_argument("--site", help="siteRef / site id")
    p.add_argument("--equip", help="equipRef (exact id)")
    p.add_argument("--equip-tag", help="comma markers the parent equip must carry, e.g. vav")
    p.add_argument("--tags", help="comma markers the record must carry")
    p.add_argument("--exclude", help="comma markers the record must NOT carry")
    p.add_argument("--class", dest="point_class", help="exact Haystack class")
    p.add_argument("--kind", choices=("all", "site", "equip", "point", "device"), default="all")
    p.add_argument("--no-live", action="store_true", help="skip merged-layer join (no latest/period)")
    p.add_argument("--format", choices=("json", "csv"), default="json")
    p.add_argument("-o", "--output", help="file (default stdout)")
    args = p.parse_args(argv)

    nf = c.NF(args.env_file, args.via)
    model = nf.query("model")
    rows = select(model, args)
    live = {}
    if not args.no_live and any(c.rec_kind(r) == "point" for r in rows):
        clauses = [c.field("markers", "point")] + ([c.field("siteRef", args.site)] if args.site else [])
        live = {r["uuid"]: r for r in nf.query("default", *clauses)}
    out = []
    for r in rows:
        row = c.flat_row(r)
        lr = live.get(r.get("uuid"))
        if lr:
            row["period"] = lr.get("period")
            row["latest_ts"], row["latest_value"] = c.latest(lr)
            row["unit"] = row["unit"] or lr.get("displayUnits")
        out.append(row)
    fh = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    c.write_rows(out, args.format, fh)
    print(f"{len(out)} records ({len(model)} in model layer)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
