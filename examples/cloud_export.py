#!/usr/bin/env python3
"""
Example: Hit Open-FDD API and print timeseries + faults.

For MSI/cloud integrators: use this as a starting point. Replace the print()
calls with your cloud API (e.g. POST to Azure IoT, AWS, SkySpark, etc.).

Usage:
  python examples/cloud_export.py
  API_BASE=http://localhost:8000 python examples/cloud_export.py
  API_BASE=http://your-openfdd:8000 python examples/cloud_export.py --site default
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


def main():
    parser = argparse.ArgumentParser(
        description="Export timeseries + faults from Open-FDD API"
    )
    parser.add_argument("--site", default="default", help="Site name or UUID")
    parser.add_argument("--days", type=int, default=7, help="Days to fetch")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    base = API_BASE.rstrip("/")

    print(
        f"=== Open-FDD cloud export example ===\nAPI: {base}\nSite: {args.site}\nRange: {start} to {end}\n"
    )

    with httpx.Client(timeout=TIMEOUT) as client:
        # --- Faults (JSON) ---
        print("[1] GET /download/faults (JSON)")
        r = client.get(
            f"{base}/download/faults",
            params={"start_date": start, "end_date": end, "format": "json"},
        )
        if r.status_code != 200:
            print(f"    Error {r.status_code}: {r.text[:200]}\n")
        else:
            data = r.json()
            faults = data.get("faults", [])
            count = data.get("count", len(faults))
            print(f"    OK: {count} fault records")
            if faults:
                for f in faults[:3]:
                    print(
                        f"      - {f.get('ts')} {f.get('site_id')} {f.get('fault_id')} flag={f.get('flag_value')}"
                    )
                if len(faults) > 3:
                    print(f"      ... and {len(faults) - 3} more")
            print()

        # --- Faults (CSV) ---
        print("[2] GET /download/faults (CSV)")
        r = client.get(
            f"{base}/download/faults",
            params={"start_date": start, "end_date": end, "format": "csv"},
        )
        if r.status_code != 200:
            print(f"    Error {r.status_code}\n")
        else:
            lines = r.text.strip().split("\n")
            print(f"    OK: {len(lines)} lines (incl. header)")
            if len(lines) > 1:
                print(f"      Header: {lines[0][:80]}...")
            print()

        # --- Fault analytics (motor runtime, data-model driven) ---
        print("[3] GET /analytics/motor-runtime")
        r = client.get(
            f"{base}/analytics/motor-runtime",
            params={"site_id": args.site, "start_date": start, "end_date": end},
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "NO DATA":
                print(f"    {data.get('status')}: {data.get('reason', '')[:60]}...")
            else:
                print(
                    f"    OK: {data.get('motor_runtime_hours', 0)} h ({data.get('point', {}).get('external_id', '?')})"
                )
        else:
            print(f"    Error {r.status_code}\n")
        print()

        # --- Timeseries (CSV) ---
        print("[4] GET /download/csv (timeseries)")
        r = client.get(
            f"{base}/download/csv",
            params={
                "site_id": args.site,
                "start_date": start,
                "end_date": end,
                "format": "wide",
            },
        )
        if r.status_code == 404:
            print("    No data (404) or site not found\n")
        elif r.status_code != 200:
            print(f"    Error {r.status_code}\n")
        else:
            lines = r.text.strip().split("\n")
            print(f"    OK: {len(lines)} rows")
            if len(lines) > 1:
                cols = lines[0].split(",")
                print(
                    f"      Columns: {len(cols)} ({', '.join(cols[:5])}{'...' if len(cols) > 5 else ''})"
                )
            print()

        # --- Fault summary ---
        print("[5] GET /analytics/fault-summary")
        r = client.get(
            f"{base}/analytics/fault-summary",
            params={"start_date": start, "end_date": end},
        )
        if r.status_code == 200:
            data = r.json()
            print(
                f"    OK: {data.get('total_faults', 0)} total, {len(data.get('by_fault_id', []))} fault types"
            )
        else:
            print(f"    Error {r.status_code}\n")
        print()

    print("--- The rest is on you ---")
    print("Send the JSON/CSV to your cloud API, data warehouse, or analytics platform.")
    print("Example: POST to your REST endpoint, write to S3, push to IoT Hub, etc.\n")


if __name__ == "__main__":
    main()
