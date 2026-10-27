#!/usr/bin/env python3
"""Post-onboarding freshness check for one NF portal site (read-only).

Reads ``NFURL`` / ``NF_CLIENT_ID`` / ``NF_CLIENT_SECRET`` from ``--env``, takes a
token from ``{NFURL}/api/v1/auth/token``, and reads the latest records with
``GET {NFURL}/api/v1/point/data`` (never POSTs data).

Point selection uses ``--sites`` (one site object or a one-element list in the
file) plus either ``--points`` (JSON list of ``equipment_id`` / ``role`` objects,
or ``EQUIP:ROLE`` lines) or repeatable ``--sample EQUIP:ROLE``. Every
``equip_type: weather`` point in the site file is always checked.

Every checked point must be numeric, newer than ``--max-age-min`` (default 30),
and within a plausibility range. Weather hook points older than ``--warn-age-min``
(default 25) print WARN but do not fail alone. Exit 0 prints PASS; FAIL exits 1.
Secrets are never printed. NF ``DEGREES_CELSIUS`` values are converted to °F
for the range check.

    python3 scripts/nf/check_portal_fresh.py --env ~/.secrets/nf_site.env \\
        --sites ~/.config/openfdd/sites/site_a.json --points probes.json
    python3 scripts/nf/check_portal_fresh.py --self-test
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# The portal answers 403 to Python's default User-Agent.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 openfdd-nf-fresh/1.0"
CHICAGO = ZoneInfo("America/Chicago")
# One 20-minute weather-hook interval plus margin. Older than this WARNs.
# --max-age-min (default 30) remains the fail threshold.
DEFAULT_WARN_AGE_MIN = 25.0

TEMP_F = (-40.0, 130.0)
RANGES = {
    "humidity": (0.0, 100.0),
    "hw-": (32.0, 220.0),
}


def plausible_range(role: str) -> tuple[float, float]:
    if "humidity" in role:
        return RANGES["humidity"]
    if role.startswith("hw-"):
        return RANGES["hw-"]
    return TEMP_F


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"FAIL: env file not found: {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        out[key] = value.strip().strip('"').strip("'")
    for key in ("NFURL", "NF_CLIENT_ID", "NF_CLIENT_SECRET"):
        if not out.get(key):
            raise SystemExit(f"FAIL: {key} missing from {path}")
    return out


def http_json(url: str, method: str = "GET", body: dict | None = None, token: str | None = None) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    path = urllib.parse.urlsplit(url).path
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        raise SystemExit(f"FAIL: {method} {path} HTTP {err.code}") from None
    except urllib.error.URLError as err:
        raise SystemExit(f"FAIL: {method} {path} {err.reason}") from None
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        raise SystemExit(f"FAIL: {method} {path} did not return JSON (wrong NFURL or UA blocked?)") from None


def fetch_units(base: str, token: str, uuids: list[str]) -> dict[str, str]:
    """uuid -> NF units string; empty when the portal does not return them."""
    out: dict[str, str] = {}
    for u in uuids:
        try:
            body = http_json(f"{base}/api/v1/point/points-id?uuids={urllib.parse.quote(u)}", token=token)
        except SystemExit:
            continue
        for pt in body.get("points") or []:
            if pt.get("uuid"):
                unit = pt.get("units") or ""
                if unit in ("", "UNITS_UNKNOWN"):
                    # hook global variables carry units only as an attr (e.g. "degF")
                    unit = {"degf": "DEGREES_FAHRENHEIT", "degc": "DEGREES_CELSIUS", "%": "PERCENT"}.get(
                        str((pt.get("attrs") or {}).get("units", "")).lower(), unit)
                out[pt["uuid"]] = unit
    return out


UNIT_LABEL = {"DEGREES_FAHRENHEIT": "degF", "DEGREES_CELSIUS": "degC", "PERCENT": "%", "PERCENT_RELATIVE_HUMIDITY": "%RH"}


def load_sample_points(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"FAIL: empty points file: {path}")
    if text.startswith("["):
        rows = json.loads(text)
        out: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise SystemExit(f"FAIL: points file entries must be objects: {path}")
            equip = str(row.get("equipment_id", "")).strip()
            role = str(row.get("role", "")).strip()
            if not equip or not role:
                raise SystemExit(f"FAIL: each points entry needs equipment_id and role: {path}")
            out.append((equip, role))
        return out
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SystemExit(f"FAIL: points line must be EQUIP:ROLE: {line}")
        equip, role = line.split(":", 1)
        out.append((equip.strip(), role.strip()))
    if not out:
        raise SystemExit(f"FAIL: no points in {path}")
    return out


def pick_points(sites_path: Path, sample: list[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    sites = json.loads(sites_path.read_text(encoding="utf-8"))
    points = [p for site in sites for p in site.get("point_map") or []]
    index = {(p["equipment_id"], p["role"]): p for p in points}
    chosen, notes = [], []
    for key in sample:
        if key in index:
            chosen.append(index[key])
        else:
            notes.append(f"note: sample {key[0]}/{key[1]} not in {sites_path.name}, skipped")
    weather = [p for p in points if p.get("equip_type") == "weather"]
    if not weather:
        notes.append(f"note: no equip_type=weather points in {sites_path.name}")
    chosen.extend(weather)
    return chosen, notes


def value_of(rec: dict) -> float | None:
    for key in ("double", "real", "signed", "unsigned"):
        if key in rec and rec[key] is not None:
            try:
                return float(rec[key])
            except (TypeError, ValueError):
                return None
    return None


def parse_ts(raw: str) -> datetime:
    # RFC3339 with up to nanoseconds; trim to microseconds for fromisoformat.
    raw = raw.replace("Z", "+00:00")
    if "." in raw:
        head, frac = raw.split(".", 1)
        tz = ""
        for sep in ("+", "-"):
            if sep in frac:
                frac, tz = frac.split(sep, 1)
                tz = sep + tz
                break
        raw = f"{head}.{frac[:6]}{tz}"
    return datetime.fromisoformat(raw)


def format_minutes(value: float) -> str:
    """Print a threshold the way it was configured, including a fraction."""
    return f"{value:g}"


def freshness_age_findings(
    name: str,
    age_min: float,
    *,
    is_weather: bool,
    warn_min: float,
    fail_min: float,
) -> tuple[str | None, str | None]:
    """Return (warn, fail) for one point. Weather warns above warn_min; any point fails above fail_min."""
    warn = None
    if is_weather and age_min > warn_min:
        warn = (
            f"{name}: last record {age_min:.1f} min old "
            f"(> {format_minutes(warn_min)}; one hook interval plus margin)"
        )
    fail = None
    if age_min > fail_min:
        fail = f"{name}: last record {age_min:.1f} min old (> {format_minutes(fail_min)})"
    return warn, fail


def run_freshness_self_test() -> int:
    """Offline checks for the 25 min weather WARN and the 30 min fail threshold."""
    cases = [
        ("weather/web-outside-air-temp", 26.0, True, True, False),
        ("weather/web-outside-air-humidity", 31.2, True, True, True),
        ("weather/web-outside-air-dewpoint", 25.0, True, False, False),
        ("rtu_01/supply-air-temp", 26.0, False, False, False),
        ("rtu_01/supply-air-temp", 30.0, False, False, False),
        ("rtu_01/supply-air-temp", 30.1, False, False, True),
    ]
    for name, age, is_weather, expect_warn, expect_fail in cases:
        warn, fail = freshness_age_findings(
            name,
            age,
            is_weather=is_weather,
            warn_min=DEFAULT_WARN_AGE_MIN,
            fail_min=30.0,
        )
        if (warn is not None) != expect_warn or (fail is not None) != expect_fail:
            print(f"SELF-TEST FAIL {name} age={age} warn={warn!r} fail={fail!r}")
            return 1
        if warn is not None and "> 25" not in warn:
            print(f"SELF-TEST FAIL warn text {warn}")
            return 1
    frac_warn, frac_fail = freshness_age_findings(
        "weather/web-outside-air-temp",
        25.6,
        is_weather=True,
        warn_min=25.5,
        fail_min=30.5,
    )
    if frac_warn is None or "> 25.5" not in frac_warn or frac_fail is not None:
        print(f"SELF-TEST FAIL fractional warn {frac_warn!r} {frac_fail!r}")
        return 1
    _, frac_fail = freshness_age_findings(
        "rtu_01/supply-air-temp",
        30.6,
        is_weather=False,
        warn_min=25.5,
        fail_min=30.5,
    )
    if frac_fail is None or "> 30.5" not in frac_fail:
        print(f"SELF-TEST FAIL fractional fail {frac_fail!r}")
        return 1
    if DEFAULT_WARN_AGE_MIN != 25.0:
        print(f"SELF-TEST FAIL DEFAULT_WARN_AGE_MIN={DEFAULT_WARN_AGE_MIN}")
        return 1
    print("SELF-TEST PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path, help="env file with NFURL, NF_CLIENT_ID, NF_CLIENT_SECRET")
    ap.add_argument("--sites", type=Path, help="provider_sites JSON for this portal (one site)")
    ap.add_argument(
        "--points",
        type=Path,
        help="probe list: JSON [{equipment_id, role}, ...] or EQUIP:ROLE lines",
    )
    ap.add_argument("--max-age-min", type=float, default=30.0)
    ap.add_argument(
        "--warn-age-min",
        type=float,
        default=DEFAULT_WARN_AGE_MIN,
        help="WARN, do not fail, when a weather hook point is older than this many minutes (default 25)",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="run the offline weather-age checks and exit (no portal access)",
    )
    ap.add_argument("--lookback-min", type=float, default=120.0)
    ap.add_argument(
        "--sample",
        action="append",
        metavar="EQUIP:ROLE",
        help="replace the default BACnet sample (repeatable), e.g. rtu_01:supply-air-temp",
    )
    args = ap.parse_args()
    if args.self_test:
        return run_freshness_self_test()

    if args.env is None or args.sites is None:
        raise SystemExit("FAIL: --env and --sites are required (or use --self-test)")

    if args.points is not None:
        sample = load_sample_points(args.points.expanduser())
    elif args.sample:
        sample = [tuple(s.split(":", 1)) for s in args.sample]  # type: ignore[misc]
    else:
        raise SystemExit("FAIL: pass --points <file> or at least one --sample EQUIP:ROLE")

    env = load_env(args.env.expanduser())
    base = env["NFURL"].rstrip("/")
    points, notes = pick_points(args.sites, sample)
    if not points:
        raise SystemExit("FAIL: no points selected")

    tok = http_json(
        f"{base}/api/v1/auth/token",
        "POST",
        {"client_id": env["NF_CLIENT_ID"], "client_secret": env["NF_CLIENT_SECRET"], "grant_type": "client_credentials"},
    )
    token = tok.get("accessToken") or tok.get("access_token")
    if not token:
        raise SystemExit("FAIL: token response had no access token")

    now = datetime.now(timezone.utc)
    q = urllib.parse.urlencode(
        {
            "from.seconds": int((now - timedelta(minutes=args.lookback_min)).timestamp()),
            "to.seconds": int(now.timestamp()) + 60,
        }
    )
    q += "".join("&uuids=" + urllib.parse.quote(p["provider_point_id"]) for p in points)
    body = http_json(f"{base}/api/v1/point/data?{q}", token=token)
    series = {item.get("uuid"): item.get("values") or [] for item in body.get("data") or []}
    units = fetch_units(base, token, [p["provider_point_id"] for p in points])

    host = urllib.parse.urlsplit(base).hostname
    print(f"portal {host}  checked {len(points)} points  now {now.astimezone(CHICAGO):%Y-%m-%d %H:%M:%S %Z}")
    for n in notes:
        print(n)
    rows, fails, warns = [], [], []
    latest_by_role: dict[str, float] = {}
    for p in points:
        name = f"{p['equipment_id']}/{p['role']}"
        vals = series.get(p["provider_point_id"], [])
        if not vals:
            rows.append((name, "-", "", "-", "-"))
            fails.append(f"{name}: no records in the last {args.lookback_min:.0f} min")
            continue
        last = max(vals, key=lambda r: parse_ts(r["ts"]))
        ts = parse_ts(last["ts"])
        age = (now - ts).total_seconds() / 60.0
        v = value_of(last)
        unit = units.get(p["provider_point_id"], "")
        rows.append((name, "null" if v is None else f"{v:.2f}", UNIT_LABEL.get(unit, "?" if unit in ("", "UNITS_UNKNOWN") else unit.lower()),
                     f"{ts.astimezone(CHICAGO):%Y-%m-%d %H:%M:%S %Z}", f"{age:.1f}"))
        warn, age_fail = freshness_age_findings(
            name,
            age,
            is_weather=p.get("equip_type") == "weather",
            warn_min=args.warn_age_min,
            fail_min=args.max_age_min,
        )
        if warn:
            warns.append(warn)
        if age_fail:
            fails.append(age_fail)
        if v is None or math.isnan(v) or math.isinf(v):
            fails.append(f"{name}: last value is null or non-numeric")
            continue
        lo, hi = plausible_range(p["role"])
        check = v * 9.0 / 5.0 + 32.0 if unit == "DEGREES_CELSIUS" else v
        if not lo <= check <= hi:
            fails.append(f"{name}: {v:.2f} outside plausible range {lo:g}..{hi:g}")
        if p.get("equip_type") == "weather":
            latest_by_role[p["role"]] = v

    dp = latest_by_role.get("web-outside-air-dewpoint")
    db = latest_by_role.get("web-outside-air-temp")
    if dp is not None and db is not None and dp > db + 0.5:
        fails.append(f"weather: dewpoint {dp:.2f} > dry bulb {db:.2f} + 0.5")

    w = max(len(r[0]) for r in rows)
    print(f"{'point':<{w}}  {'last value':>10}  {'units':<5}  {'last timestamp (America/Chicago)':<32}  {'age min':>7}")
    for r in rows:
        print(f"{r[0]:<{w}}  {r[1]:>10}  {r[2]:<5}  {r[3]:<32}  {r[4]:>7}")
    if warns:
        print("WARN")
        for item in warns:
            print(f"  - {item}")
    if fails:
        print("FAIL")
        for item in fails:
            print(f"  - {item}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
