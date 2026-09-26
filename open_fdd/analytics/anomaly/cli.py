"""``open-fdd-anomaly`` — offline screening of a history_wide device folder.

Example::

    open-fdd-anomaly screen ./AHU_1 --out ./anomaly_out

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
            "with rolling Z-score, rolling MAD, STL residual, and Isolation Forest."
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0

    if args.command != "screen":
        parser.print_help()
        return 2

    from open_fdd.analytics.anomaly.screen import screen_folder

    methods = [part.strip().lower() for part in str(args.methods).split(",") if part.strip()]
    try:
        screen_folder(
            args.folder,
            args.out,
            top_n=int(args.top_n),
            max_days=int(args.max_days),
            methods=methods,
            command="open-fdd-anomaly " + " ".join(argv if argv is not None else sys.argv[1:]),
        )
    except NotImplementedError:
        print("screen is not implemented yet", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
