#!/usr/bin/env python3
"""
Cloud export example: pull fault and timeseries data from the Open-FDD API.

This script is a **starting place** for how vendor X, Y, or Z (cloud FDD providers,
MSI, commissioning firms, IoT contractors) can use Open-FDD to get data to their
cloud for deeper insights. Open-FDD runs behind the firewall and does not push
data out; your process runs on the building or OT network, pulls from the API
over the LAN, then sends to your cloud (REST POST, S3, IoT Hub, SkySpark, etc.).

Replace the print/output handling with your own cloud send logic. See
docs/concepts/cloud_export.md and the "Behind the firewall; cloud export is
vendor-led" section on the docs home.

Usage:
  python examples/cloud_export.py
  python examples/cloud_export.py --site default --days 14
  API_BASE=http://your-openfdd:8000 python examples/cloud_export.py
"""

import argparse
import os
import sys
from datetime import date, timedelta

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
TIMEOUT = 60.0


def _get(client, base, path, params):
    """GET and return (response, None) or (None, error_message)."""
    r = client.get(f"{base}{path}", params=params)
    if r.status_code == 200:
        return r, None
    if r.status_code == 404:
        return None, "404 (no data or site not found)"
    return None, f"{r.status_code}: {r.text[:150]}"


def main():
    parser = argparse.ArgumentParser(
        description="Export timeseries + faults from Open-FDD API (cloud vendor starting point)"
    )
    parser.add_argument("--site", default="default", help="Site name or UUID")
    parser.add_argument("--days", type=int, default=7, help="Days to fetch")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    base = API_BASE.rstrip("/")
    fault_params = {"start_date": start, "end_date": end}

    print(
        f"=== Open-FDD cloud export example ===\n"
        f"API: {base}\nSite: {args.site}\nRange: {start} to {end}\n"
    )

    with httpx.Client(timeout=TIMEOUT) as client:
        # 1. Faults (JSON)
        print("[1] GET /download/faults (JSON)")
        r, err = _get(
            client, base, "/download/faults", {**fault_params, "format": "json"}
        )
        if err:
            print(f"    {err}\n")
        else:
            data = r.json()
            faults = data.get("faults", [])
            count = data.get("count", len(faults))
            print(f"    OK: {count} fault records")
            for f in faults[:3]:
                print(
                    f"      - {f.get('ts')} {f.get('site_id')} "
                    f"{f.get('fault_id')} flag={f.get('flag_value')}"
                )
            if len(faults) > 3:
                print(f"      ... and {len(faults) - 3} more")
            print()

        # 2. Faults (CSV)
        print("[2] GET /download/faults (CSV)")
        r, err = _get(
            client, base, "/download/faults", {**fault_params, "format": "csv"}
        )
        if err:
            print(f"    {err}\n")
        else:
            lines = r.text.strip().split("\n")
            print(f"    OK: {len(lines)} lines (incl. header)")
            if lines:
                print(f"      Header: {lines[0][:80]}...")
            print()

        # 3. Motor runtime (data-model driven)
        print("[3] GET /analytics/motor-runtime")
        r, err = _get(
            client,
            base,
            "/analytics/motor-runtime",
            {
                "site_id": args.site,
                "start_date": start,
                "end_date": end,
            },
        )
        if err:
            print(f"    {err}\n")
        else:
            data = r.json()
            if data.get("status") == "NO DATA":
                print(f"    NO DATA: {data.get('reason', '')[:60]}...")
            else:
                pt = data.get("point", {})
                print(
                    f"    OK: {data.get('motor_runtime_hours', 0)} h "
                    f"({pt.get('external_id', '?')})"
                )
            print()

        # 4. Timeseries (CSV)
        print("[4] GET /download/csv (timeseries)")
        r, err = _get(
            client,
            base,
            "/download/csv",
            {
                "site_id": args.site,
                "start_date": start,
                "end_date": end,
                "format": "wide",
            },
        )
        if err:
            print(f"    {err}\n")
        else:
            lines = r.text.strip().split("\n")
            print(f"    OK: {len(lines)} rows")
            if len(lines) > 1:
                cols = lines[0].split(",")
                suffix = "..." if len(cols) > 5 else ""
                print(f"      Columns: {len(cols)} ({', '.join(cols[:5])}{suffix})")
            print()

        # 5. Fault summary
        print("[5] GET /analytics/fault-summary")
        r, err = _get(
            client,
            base,
            "/analytics/fault-summary",
            fault_params,
        )
        if err:
            print(f"    {err}\n")
        else:
            data = r.json()
            by_id = data.get("by_fault_id", [])
            print(
                f"    OK: {data.get('total_faults', 0)} total, "
                f"{len(by_id)} fault types"
            )
            print()

    print("--- Next: send data to your cloud ---")
    print(
        "Replace this script's output with your pipeline: POST to your API, "
        "write to S3, push to IoT Hub, etc. See docs/concepts/cloud_export.md\n"
    )


if __name__ == "__main__":
    main()
