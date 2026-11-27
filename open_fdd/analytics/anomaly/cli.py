"""``open-fdd-anomaly`` — offline screening of a history_wide device folder.

Example::

    open-fdd-anomaly screen ./AHU_1 --out ./anomaly_out
    open-fdd-anomaly report ./AHU_1 --out ./ahu1_report --month 2026-06 --compile \\
        --location "AHU · Example Campus · City, ST"

``report --compile`` writes ``report.pdf`` in the output directory when the
``typst`` binary is on ``PATH``.

Defaults: ``--top-n 5 --max-days 10``; methods ``zscore,mad,stl``, each only when its dependency
imports (a skipped default is listed in the README). Z-score and MAD are SQL-portable
(pandas/numpy). STL (statsmodels) and Isolation Forest (scikit-learn) are Python-only and need
``pip install "open-fdd[anomaly]"``. Isolation Forest is opt-in (``--methods ...,iforest``): it
flags a fixed fraction of every point by construction.

``screen --engine sql`` computes the z-score with ``sql/analytics/anomaly_zscore.sql``
on an in-process SQLite core (standard library), the query Open-FDD databases run
(issue #1649); flags match the pandas detector on each point's non-missing samples.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_METHODS = "zscore,mad,stl"
METHODS_HELP = (
    "Comma-separated detectors. zscore, mad: pandas only. stl: needs statsmodels, "
    "iforest: needs scikit-learn (both in pip install \"open-fdd[anomaly]\"). "
    "Default: zscore,mad,stl, skipping stl when statsmodels is missing. iforest is opt-in: it flags "
    "--iforest-contamination of every point by construction"
)


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
        default=None,
        help=METHODS_HELP,
    )
    screen.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help="Print the run summary as JSON on stdout, or write it to PATH (summary.json is always written to --out)",
    )
    screen.add_argument("--no-plots", action="store_true", help="Skip every PNG (scoreboard, support plots, day zooms)")
    screen.add_argument(
        "--tz",
        default="UTC",
        help="IANA zone for calendar days, day zooms and JSON windows, e.g. America/Chicago (default UTC)",
    )
    screen.add_argument(
        "--iforest-contamination",
        type=float,
        default=0.01,
        help="Fraction of samples iforest flags on every point (default 0.01)",
    )
    screen.add_argument(
        "--engine",
        choices=("pandas", "sql"),
        default="pandas",
        help="Where the z-score runs: pandas (default) or sql (sql/analytics/anomaly_zscore.sql)",
    )
    screen.add_argument(
        "--sql-engine",
        choices=("duckdb",),
        default="duckdb",
        help=(
            "With --engine sql, the in-process database (duckdb>=2.0.1). Timescale uses "
            "open_fdd.analytics.sql_anomaly.run_zscore_sql(conn, engine='timescale') on a connection "
            "that already has fdd.point and fdd.input_sample"
        ),
    )
    screen.add_argument(
        "--activity",
        choices=("proof", "ungated"),
        default="proof",
        help=(
            "proof (default): screen equipment points only while operating proof is on, the same policy as "
            "open-fdd-ml detect; site/weather points are always screened. ungated: screen every row on purpose"
        ),
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
        "--units",
        choices=("imperial", "si"),
        default="imperial",
        help="Display preference for plot axes and Typst captions (storage stays SI when declared)",
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
        help='Site line under the title. Example: "AHU · Example Campus · City, ST". Empty unless passed.',
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

    methods = (
        None
        if args.methods is None
        else [part.strip().lower() for part in str(args.methods).split(",") if part.strip()]
    )
    command = "open-fdd-anomaly " + " ".join(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "screen":
            from open_fdd.analytics.anomaly.screen import screen_folder

            result = screen_folder(
                args.folder,
                args.out,
                top_n=int(args.top_n),
                max_days=int(args.max_days),
                methods=methods,
                command=command,
                engine=str(args.engine),
                sql_engine=str(args.sql_engine),
                activity_policy=str(args.activity),
                iforest_contamination=float(args.iforest_contamination),
                plots=not bool(args.no_plots),
                tz=str(args.tz),
            )
            if args.json:
                import json

                text = json.dumps(result.summary, indent=1, default=str)
                if args.json == "-":
                    print(text)
                else:
                    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.json).write_text(text, encoding="utf-8")
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
                units=args.units,
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
