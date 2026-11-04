#!/usr/bin/env python3
"""Apply Haystack tag changes to the NF *model* layer. DRY-RUN BY DEFAULT.

Input: a JSON plan file, a list of {"uuid": ..., "attrs": {...}, "period": "300"?}.
`attrs` are merged over the point's current model-layer attrs (set a key to
null to drop it). The tool prints a diff; it only writes with --apply.

Guard rails:
  * layer is always "model" (never hpl:* / default), so no BACnet/control writes.
  * keys that look like control/conversion/schedule data are refused
    (present value, priority, write, conversion, schedule, cov).
  * a "period" in the plan is refused unless --set-trend-period is given.
  * every uuid must exist in the model layer, and with --site must carry that siteRef.

  nf_tag_apply.py --env-file ~/.secrets/nf_acme.env --site acme plan.json            # dry-run
  nf_tag_apply.py --env-file ~/.secrets/nf_acme.env --site acme plan.json --apply    # EXPERIMENTAL write
NOTE: the write path (POST /api/v1/point/points, layer=model) mirrors the NF
REST UpdatePoints call; confirm on your NF version with one point first.
--apply is EXPERIMENTAL: POST /api/v1/point/points is not confirmed in NF docs.
"""
from __future__ import annotations

import argparse
import json
import sys

import nf_common as c

FORBIDDEN = ("present_value", "presentvalue", "priority", "write", "conversion", "schedule", "cov")


def check_attrs(attrs: dict) -> list[str]:
    return [k for k in attrs if any(f in k.lower().replace("-", "_") for f in FORBIDDEN)]


def plan_changes(plan: list[dict], model: dict, site: str | None, allow_period: bool) -> tuple[list[dict], list[str]]:
    changes, errors = [], []
    for item in plan:
        uid = item.get("uuid")
        rec = model.get(uid)
        if not rec:
            errors.append(f"{uid}: not in model layer"); continue
        cur = dict(c.attrs(rec))
        if site and cur.get("siteRef") != site:
            errors.append(f"{uid}: siteRef {cur.get('siteRef')!r} != {site!r}"); continue
        bad = check_attrs(item.get("attrs") or {})
        if bad:
            errors.append(f"{uid}: refused control/conversion keys {bad}"); continue
        extra = set(item) - {"uuid", "attrs", "period"}
        if extra:
            errors.append(f"{uid}: unsupported keys {sorted(extra)}"); continue
        if "period" in item and not allow_period:
            errors.append(f"{uid}: period change refused (use --set-trend-period)"); continue
        new = dict(cur)
        for k, v in (item.get("attrs") or {}).items():
            if v is None:
                new.pop(k, None)
            else:
                new[k] = str(v)
        diff = {k: (cur.get(k), new.get(k)) for k in set(cur) | set(new) if cur.get(k) != new.get(k)}
        if diff or "period" in item:
            changes.append({"uuid": uid, "name": rec.get("name"), "attrs": new, "diff": diff,
                            **({"period": str(item["period"])} if "period" in item else {})})
    return changes, errors


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plan")
    p.add_argument("--env-file")
    p.add_argument("--via", choices=tuple(c.PATHS), default="portal")
    p.add_argument("--site", help="require every point to carry this siteRef")
    p.add_argument(
        "--apply",
        action="store_true",
        help="EXPERIMENTAL: POST /api/v1/point/points (unconfirmed in NF docs); default is dry-run",
    )
    p.add_argument("--set-trend-period", action="store_true", help="allow 'period' entries")
    args = p.parse_args(argv)

    plan = json.load(open(args.plan, encoding="utf-8"))
    nf = c.NF(args.env_file, args.via)
    model = {r["uuid"]: r for r in nf.query("model")}
    changes, errors = plan_changes(plan, model, args.site, args.set_trend_period)
    for e in errors:
        print("REFUSED", e, file=sys.stderr)
    for ch in changes:
        print(json.dumps({"uuid": ch["uuid"], "name": ch["name"], "diff": ch["diff"],
                          "period": ch.get("period")}, default=str))
    if errors:
        print(f"{len(errors)} refused; nothing written", file=sys.stderr)
        return 2
    if not args.apply:
        print(f"DRY RUN: {len(changes)} point(s) would change. Re-run with --apply.", file=sys.stderr)
        return 0
    body = {"layer": "model", "points": [
        {"uuid": ch["uuid"], "layer": "model", "attrs": ch["attrs"],
         **({"period": ch["period"] + "s"} if "period" in ch else {})} for ch in changes]}
    c._request(f"{nf.base}/api/v1/point/points", body, nf.token)
    print(f"wrote {len(changes)} point(s) to model layer", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
