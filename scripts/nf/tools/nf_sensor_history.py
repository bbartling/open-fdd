#!/usr/bin/env python3
"""Pull history for one Haystack-tagged point from NF and summarize it (optionally to CSV).

Same settings and LAN / portal paths as nf_portal_sensors.py. The point is picked by markers only
(every listed marker must be on it, plus `point` and `his`), never by name or uuid. If more than one
point matches, the candidates are listed so you can add a marker or --exclude one. Samples come from
/api/v1/point/data in day-sized chunks.

Examples:

  python3 scripts/nf/tools/nf_sensor_history.py discharge,air,temp,sensor --env ~/.secrets/nf_api.env
  python3 scripts/nf/tools/nf_sensor_history.py outside,air,temp --exclude weather --days 7
  python3 scripts/nf/tools/nf_sensor_history.py weather,outside,air,temp --via portal --csv wx.csv

NF keeps about 7 days of history in Redis and caps each response at 10000 samples per point, so a
longer --days than your retention just returns what exists. Exit 1 when no point or no samples match.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import nf_common as nf


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _parse_ts(raw: str) -> datetime:
    # NF returns nanosecond precision; fromisoformat wants at most micro.
    head, _, frac = raw.rstrip("Z").partition(".")
    frac = (frac + "000000")[:6]
    return datetime.fromisoformat(f"{head}.{frac}+00:00")


def find_point(base: str, token: str, tags: list[str], exclude: list[str]) -> dict:
    clauses = [nf.field("markers", t) for t in ("point", "his", *tags)]
    matches = [
        p for p in nf.query(base, token, "default", *clauses)
        if not set(exclude) & set(nf.markers(p))
    ]
    if not matches:
        raise SystemExit(f"no trended point tagged {' '.join(tags)} on {base}")
    if len(matches) > 1:
        listing = "\n".join(
            f"   {' '.join(nf.markers(p))}  ({(p.get('attrs') or {}).get('dis', p.get('name'))})"
            for p in matches)
        raise SystemExit(f"{len(matches)} points tagged {' '.join(tags)}; add a marker or --exclude:\n{listing}")
    return matches[0]


def fetch_history(base: str, token: str, uuid: str, start: datetime,
                  end: datetime) -> list[tuple[datetime, float]]:
    samples: list[tuple[datetime, float]] = []
    chunk = start
    while chunk < end:
        chunk_end = min(chunk + timedelta(days=1), end)
        query = urlencode({"from": _iso(chunk), "to": _iso(chunk_end), "uuids": uuid})
        body = nf.request(f"{base}/api/v1/point/data?{query}", None, token)
        for series in body.get("data") or []:
            for sample in series.get("values") or []:
                value = sample.get("double")
                if value is None:
                    value = sample.get("real")
                if value is None or not sample.get("ts"):
                    continue
                samples.append((_parse_ts(sample["ts"]), float(value)))
        chunk = chunk_end
    samples.sort()
    return samples


def print_summary(samples: list[tuple[datetime, float]], units: str) -> None:
    values = [v for _, v in samples]
    lo = min(samples, key=lambda s: s[1])
    hi = max(samples, key=lambda s: s[1])
    print(f"   samples  {len(samples)}  ({_iso(samples[0][0])} to {_iso(samples[-1][0])})")
    print(f"   mean     {statistics.fmean(values):.2f} {units}")
    print(f"   min      {lo[1]:.2f} @ {_iso(lo[0])}")
    print(f"   max      {hi[1]:.2f} @ {_iso(hi[0])}")

    # A local-time daily rollup reads better than UTC for a site in one zone.
    by_day: dict[str, list[float]] = defaultdict(list)
    for ts, value in samples:
        by_day[ts.astimezone().strftime("%a %m-%d")].append(value)
    print("\n   day (local)   min     mean    max     n")
    for day, vals in by_day.items():
        print(f"   {day:12} {min(vals):6.2f}  {statistics.fmean(vals):6.2f}  "
              f"{max(vals):6.2f}  {len(vals):5}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tags", help="comma list of required markers, e.g. discharge,air,temp,sensor")
    parser.add_argument("--exclude", default="", help="comma list of markers the point must NOT have")
    parser.add_argument("--days", type=float, default=3, help="history window in days (default 3)")
    parser.add_argument("--via", choices=tuple(nf.PATHS), default="lan", help="network path (default lan)")
    parser.add_argument("--csv", type=Path, help="also write ts_utc,value,units rows here")
    nf.add_env_arg(parser)
    args = parser.parse_args(argv)
    nf.console_utf8()

    try:
        client_id, client_secret = nf.load_settings(args.env)
        base = nf.base_url(args.via)
        tags, exclude = nf.split_csv(args.tags), nf.split_csv(args.exclude)
        token = nf.bearer_token(base, client_id, client_secret)
        point = find_point(base, token, tags, exclude)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    attrs = point.get("attrs") or {}
    units = attrs.get("unit") or point.get("units") or ""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    print(f"== {attrs.get('dis') or point.get('name')} via {args.via.upper()}: {base}")
    print(f"   tags {' '.join(nf.markers(point))}  equipRef {attrs.get('equipRef', '-')}")
    print(f"   point {point.get('uuid')}  units {units}  last {args.days:g} days")
    try:
        samples = fetch_history(base, token, point["uuid"], start, end)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    if not samples:
        print("   no history in that window: is NF trending this point?", file=sys.stderr)
        return 1
    print_summary(samples, units)

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ts_utc", "value", "units"])
            writer.writerows((_iso(ts), value, units) for ts, value in samples)
        print(f"\n   wrote {len(samples)} rows to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
