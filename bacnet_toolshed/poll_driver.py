"""
BACnet RPM poll driver → local CSV (long format) for Open-FDD ingest / FDD.

  python -m bacnet_toolshed.poll_driver \\
    --config workspace/bacnet/commissioning/points.csv \\
    --interval 60 \\
    --name OpenFddEdge --instance 599999 --address 192.168.1.10/24:47808 \\
    --route-aware --network 1 --router-ip 192.168.1.1 --mstp-net 2000
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.app import Application

from bacnet_toolshed.config import group_by_device, load_enabled_points, validate_points
from bacnet_toolshed.paths import polls_dir, ensure_layout
from bacnet_toolshed.rpm import read_multiple_chunked

_log = logging.getLogger(__name__)

POLL_CSV_FIELDS = [
    "timestamp_utc",
    "site_id",
    "building_id",
    "system_id",
    "point_id",
    "series_id",
    "device_instance",
    "object_type",
    "object_instance",
    "value",
    "units",
]


def _append_poll_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POLL_CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


async def poll_once(
    app,
    points_by_device,
    *,
    output_csv: Path,
    dry_run: bool,
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    device_keys = list(points_by_device.keys())

    async def _poll_device(device_key, pts):
        dev_inst, dev_addr = device_key
        rpm_objects = {p.rpm_key(): ["present-value"] for p in pts}
        values = await read_multiple_chunked(app, dev_addr, rpm_objects)
        count = 0
        for p in pts:
            val = values.get(p.rpm_key())
            if val is None:
                continue
            row = {
                "timestamp_utc": ts,
                "site_id": p.site_id,
                "building_id": p.building_id,
                "system_id": p.system_id,
                "point_id": p.point_id,
                "series_id": p.series_id,
                "device_instance": str(p.device_instance),
                "object_type": p.object_type,
                "object_instance": str(p.object_instance),
                "value": str(val),
                "units": p.units,
            }
            if dry_run:
                print(f"DRY-RUN {p.point_id}={val}")
            else:
                rows.append(row)
            count += 1
        return count

    results = await asyncio.gather(
        *[_poll_device(k, points_by_device[k]) for k in device_keys],
        return_exceptions=True,
    )
    total = 0
    for r in results:
        if isinstance(r, Exception):
            _log.warning("poll device error: %s", r)
            print(f"poll error: {r}", file=sys.stderr)
        elif isinstance(r, int):
            total += r

    if rows and not dry_run:
        _append_poll_rows(output_csv, rows)
        _log.info("BACnet scrape wrote %d samples → %s", len(rows), output_csv)
    elif dry_run:
        _log.info("BACnet scrape dry-run %d samples (not written)", len(rows))
    return total


async def run_driver(
    config_path: Path,
    *,
    interval_s: float,
    dry_run: bool,
    output_csv: Path,
    site_id: str | None,
    building_id: str | None,
    once: bool,
    bacnet_args=None,
) -> None:
    defaults = {}
    if site_id:
        defaults["site_id"] = site_id
    if building_id:
        defaults["building_id"] = building_id

    points = load_enabled_points(config_path, defaults=defaults or None)
    errors = validate_points(points)
    if errors:
        raise SystemExit("config errors:\n  " + "\n  ".join(errors))

    parser = SimpleArgumentParser()
    if bacnet_args is None:
        bacnet_args = parser.parse_args([])

    app = Application.from_args(bacnet_args)
    points_by_device = group_by_device(points)
    ensure_layout()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _log.info(
        "BACnet poll driver start: %d points, %d devices, interval=%.0fs output=%s dry_run=%s",
        len(points),
        len(points_by_device),
        interval_s,
        output_csv,
        dry_run,
    )
    print(
        f"BACnet poll driver: {len(points)} points, {len(points_by_device)} devices, "
        f"interval={interval_s}s output={output_csv} dry_run={dry_run}",
        file=sys.stderr,
    )

    try:
        while True:
            t0 = time.perf_counter()
            n = await poll_once(app, points_by_device, output_csv=output_csv, dry_run=dry_run)
            elapsed = time.perf_counter() - t0
            _log.info("BACnet poll cycle: %d samples in %.1fs", n, elapsed)
            print(f"polled {n} samples in {elapsed:.1f}s → {output_csv}", file=sys.stderr)
            if once:
                break
            await asyncio.sleep(max(0.0, interval_s - elapsed))
    finally:
        app.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="BACnet RPM poll → local CSV")
    ap.add_argument("--config", required=True, help="Enabled points CSV (points.csv)")
    ap.add_argument("--interval", type=float, default=30.0, help="Poll interval seconds")
    ap.add_argument("--once", action="store_true", help="Single poll then exit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Append long-format samples (default: workspace/bacnet/polls/samples.csv)",
    )
    ap.add_argument("--site-id")
    ap.add_argument("--building-id")
    ap.add_argument("--route-aware", action="store_true")
    ap.add_argument("--network", type=int, default=1)
    ap.add_argument("--router-ip")
    ap.add_argument("--mstp-net", type=int)
    args, bacnet_argv = ap.parse_known_args()

    bacnet_extra: list[str] = []
    if args.route_aware:
        bacnet_extra.append("--route-aware")
    if args.network is not None:
        bacnet_extra.extend(["--network", str(args.network)])

    bacnet_parser = SimpleArgumentParser()
    bacnet_args = bacnet_parser.parse_args(bacnet_extra + bacnet_argv)

    out = args.output or (polls_dir() / "samples.csv")

    asyncio.run(
        run_driver(
            Path(args.config),
            interval_s=args.interval,
            dry_run=args.dry_run,
            output_csv=out,
            site_id=args.site_id,
            building_id=args.building_id,
            once=args.once,
            bacnet_args=bacnet_args,
        )
    )


if __name__ == "__main__":
    main()
