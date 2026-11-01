#!/usr/bin/env python3
"""Tag-driven NF queries: latest values, or history + stats over a window.

Points are picked by tags only (site, parent-equip markers, point markers,
class). Read-only: auth/token, point/query, point/data.

  nf_query.py latest  --env-file ~/.secrets/nf_acme.env --site acme --equip-tag vav --point-class discharge-air-temp-sensor
  nf_query.py history --env-file ~/.secrets/nf_acme.env --site acme --tags cool,pid --from 24h --to now
  nf_query.py history --env-file ~/.secrets/nf_bosspi.env --tags discharge,air,temp,sensor --from 2026-10-31T00:00 --raw --format csv -o dat.csv
"""
from __future__ import annotations

import argparse
import statistics
import sys

import nf_common as c


def stats(samples: list[tuple]) -> dict:
    if not samples:
        return {"n": 0}
    vals = [v for _, v in samples]
    lo = min(samples, key=lambda s: s[1])
    hi = max(samples, key=lambda s: s[1])
    return {"n": len(vals), "first_ts": c.iso(samples[0][0]), "last_ts": c.iso(samples[-1][0]),
            "min": lo[1], "min_ts": c.iso(lo[0]), "max": hi[1], "max_ts": c.iso(hi[0]),
            "mean": round(statistics.fmean(vals), 4), "last": samples[-1][1]}


def pick(nf: "c.NF", args) -> list[dict]:
    tags = ["point", *c.split_list(args.tags)]
    clauses = [c.field("markers", t) for t in tags]
    if args.site:
        clauses.append(c.field("siteRef", args.site))
    pts = nf.query("default", *clauses)
    eq_ids = None
    if args.equip_tag:
        eq_ids = c.equip_ids_with_tags(nf.query("model", c.field("markers", "equip")),
                                       c.split_list(args.equip_tag), args.site)
    return [p for p in pts if c.point_matches(p, site=args.site, equip=args.equip, tags=tags,
                                              exclude=c.split_list(args.exclude),
                                              point_class=args.point_class, equip_ids=eq_ids)]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode", choices=("latest", "history"))
    p.add_argument("--env-file")
    p.add_argument("--via", choices=tuple(c.PATHS), default="portal")
    p.add_argument("--site")
    p.add_argument("--equip")
    p.add_argument("--equip-tag")
    p.add_argument("--tags")
    p.add_argument("--exclude")
    p.add_argument("--point-class")
    p.add_argument("--from", dest="start", default="24h", help="ISO or relative (24h, 3d)")
    p.add_argument("--to", dest="end", default="now")
    p.add_argument("--raw", action="store_true", help="history: emit every sample, not stats")
    p.add_argument("--limit", type=int, default=200, help="max points (safety)")
    p.add_argument("--format", choices=("json", "csv"), default="json")
    p.add_argument("-o", "--output")
    args = p.parse_args(argv)

    nf = c.NF(args.env_file, args.via)
    pts = pick(nf, args)
    if len(pts) > args.limit:
        raise SystemExit(f"{len(pts)} points match; narrow the tags or raise --limit")
    rows = []
    if args.mode == "latest":
        rows = [c.flat_row(x) | {"period": x.get("period")} for x in pts]
    else:
        start, end = c.parse_when(args.start), c.parse_when(args.end)
        for x in pts:
            a = c.attrs(x)
            base = {"uuid": x["uuid"], "dis": a.get("dis") or x.get("name"), "equipRef": a.get("equipRef"),
                    "class": a.get("class"), "unit": a.get("unit") or x.get("displayUnits")}
            samples = nf.history(x["uuid"], start, end)
            if args.raw:
                rows += [base | {"ts": c.iso(t), "value": v} for t, v in samples]
            else:
                rows.append(base | stats(samples))
    fh = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    c.write_rows(rows, args.format, fh)
    print(f"{len(pts)} points matched, {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
