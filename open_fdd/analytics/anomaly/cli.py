"""``open-fdd-anomaly`` — offline screening of a history_wide device folder.

Example::

    open-fdd-anomaly screen ./AHU_1 --out ./anomaly_out
    open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --compile \\
        --location "AHU · ACME Office · Detroit, MI"

``report --compile`` writes ``report.pdf`` in the output directory when the
``typst`` binary is on ``PATH``.

Defaults: ``--top-n 5 --max-days 10 --methods zscore,mad,stl,iforest``.
Z-score and MAD are SQL-portable (pandas/numpy). STL and Isolation Forest
are Python-only and require ``pip install "open-fdd[anomaly]"``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_METHODS = "zscore,mad,stl,iforest"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-fdd-anomaly",
        description=(
            "Screen AHU IO points in a device folder (history_wide.csv + column_map.json) "
            "and optionally write a single-system FDD/RCx Typst report."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    screen = sub.add_parser(
        "screen",
        help="Screen one device folder and write scoreboard, support plots, and day zooms",
    )
    screen.add_argument(
        "folder",
        type=Path,
        help="Device folder containing history_wide.csv and column_map.json",
    )
    screen.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for scoreboard, plots, and README",
    )
    screen.add_argument("--top-n", type=int, default=5, help="Noisiest points to day-zoom (default 5)")
    screen.add_argument(
        "--max-days",
        type=int,
        default=10,
        help="Worst calendar days (UTC) per top point (default 10)",
    )
    screen.add_argument(
        "--methods",
        default=DEFAULT_METHODS,
        help=f"Comma-separated detectors (default {DEFAULT_METHODS})",
    )
    report = sub.add_parser(
        "report",
        help="Offline single-system or building-folder AHU FDD/RCx Typst sources",
    )
    report.add_argument(
        "folder",
        type=Path,
        help="Device folder, or a building folder of device subfolders",
    )
    report.add_argument("--out", type=Path, required=True, help="Output directory")
    report.add_argument(
        "--scope",
        choices=("single-system", "building"),
        default="single-system",
        help="single-system (one AHU folder) or building (child device folders)",
    )
    report.add_argument(
        "--month",
        default=None,
        help="Calendar month YYYY-MM. Default: month with the most samples (fixture example 2026-06)",
    )
    report.add_argument(
        "--web-oat",
        default=None,
        help="Web OAT CSV path, or 'fetch' with --lat and --lon (Open-Meteo). A mapped web-outside-air-temp column is used first.",
    )
    report.add_argument("--lat", type=float, default=None, help="Latitude for --web-oat fetch")
    report.add_argument("--lon", type=float, default=None, help="Longitude for --web-oat fetch")
    report.add_argument(
        "--week",
        default=None,
        help=(
            "RCx week start YYYY-MM-DD (UTC), seven days from that date. "
            "April example: 2026-04-06 (through 2026-04-12). "
            "Default: the 7-day window in the month with the most fan-on samples."
        ),
    )
    report.add_argument("--top-n", type=int, default=5, help="Unused by report (screen command)")
    report.add_argument("--max-days", type=int, default=10, help="Unused by report (screen command)")
    report.add_argument(
        "--methods",
        default=DEFAULT_METHODS,
        help="Unused by report (screen command)",
    )
    report.add_argument(
        "--profile",
        default=None,
        help=(
            "System profile id. Default follows equipType. "
            "Implemented today: vav_ahu and cv_ahu (same air-side figures; unit ventilator is cv_ahu). "
            "Registered stubs include single_zone, "
            "chiller, boiler, heat_pump, vav_box, fan_coil, geothermal_field, data_hall."
        ),
    )
    report.add_argument(
        "--compile",
        action="store_true",
        help="Write report.pdf in --out. This CLI flag is the only PDF path; typst must be on PATH",
    )
    report.add_argument(
        "--title",
        default=None,
        help='Report title. Default: "Open-FDD AI Agent Report"',
    )
    report.add_argument(
        "--location",
        default=None,
        help='Site line under the title. Example: "AHU · ACME Office · Detroit, MI"',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0

    if args.command not in {"screen", "report"}:
        parser.print_help()
        return 2

    methods = [part.strip().lower() for part in str(args.methods).split(",") if part.strip()]
    command = "open-fdd-anomaly " + " ".join(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "screen":
            from open_fdd.analytics.anomaly.screen import screen_folder

            screen_folder(
                args.folder,
                args.out,
                top_n=int(args.top_n),
                max_days=int(args.max_days),
                methods=methods,
                command=command,
            )
        else:
            from open_fdd.reporting.single_system_typst import build_single_system_report

            result = build_single_system_report(
                args.folder,
                args.out,
                scope=args.scope,
                month=args.month,
                web_oat=args.web_oat,
                lat=args.lat,
                lon=args.lon,
                week=args.week,
                profile=args.profile,
                title=args.title,
                location=args.location,
                top_n=int(args.top_n),
                max_days=int(args.max_days),
                methods=methods,
                command=command,
                compile_pdf=bool(args.compile),
            )
            pdf_path = getattr(result, "pdf_path", None)
            if pdf_path is not None:
                print(pdf_path)
    except NotImplementedError:
        print("screen is not implemented yet", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
