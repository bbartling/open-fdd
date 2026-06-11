"""Package-focused CLI — lint/test/run Arrow rules (not Docker/BACnet deploy)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import open_fdd


def _cmd_version(_: argparse.Namespace) -> int:
    print(open_fdd.__version__)
    return 0


def _cmd_lint_rule(args: argparse.Namespace) -> int:
    from open_fdd.playground.sandbox import lint_python

    code = Path(args.rule).read_text(encoding="utf-8")
    result = lint_python(code)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _cmd_test_rule(args: argparse.Namespace) -> int:
    import pyarrow.feather as feather

    from open_fdd.arrow_runtime import run_arrow_rule

    code = Path(args.rule).read_text(encoding="utf-8")
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    table = feather.read_table(args.input)
    result = run_arrow_rule(code, table, cfg, rule_id=Path(args.rule).stem)
    print(
        json.dumps(
            {
                "ok": not result.errors,
                "true_count": result.true_count,
                "false_count": result.false_count,
                "errors": result.errors,
                "warnings": result.warnings,
            },
            indent=2,
        )
    )
    return 0 if not result.errors else 1


def _cmd_run_arrow(args: argparse.Namespace) -> int:
    import pyarrow.feather as feather

    from open_fdd.arrow_runtime import run_arrow_rule

    code = Path(args.rule).read_text(encoding="utf-8")
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    table = feather.read_table(args.input)
    result = run_arrow_rule(code, table, cfg, rule_id=Path(args.rule).stem, include_output_table=True)
    if result.errors:
        print(json.dumps({"errors": result.errors}, indent=2), file=sys.stderr)
        return 1
    if args.output and result.output_table is not None:
        out = result.output_table
        if args.output.endswith(".parquet"):
            import pyarrow.parquet as pq

            pq.write_table(out, args.output)
        else:
            feather.write_feather(out, args.output)
    print(json.dumps({"true_count": result.true_count, "output": args.output}, indent=2))
    return 0


def _cmd_validate_rule_pack(args: argparse.Namespace) -> int:
    from open_fdd.playground.sandbox import lint_python

    root = Path(args.rules_dir)
    failures: list[str] = []
    for path in sorted(root.glob("*.py")):
        lint = lint_python(path.read_text(encoding="utf-8"))
        if not lint.get("ok"):
            failures.append(f"{path.name}: {lint.get('issues')}")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    print(f"OK: {len(list(root.glob('*.py')))} rules")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="open-fdd",
        description="Arrow-native FDD rule lint, test, and batch run (PyPI package).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {open_fdd.__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Print package version").set_defaults(func=_cmd_version)

    p_lint = sub.add_parser("lint-rule", help="Lint an apply_faults_arrow rule file")
    p_lint.add_argument("rule", type=Path)
    p_lint.set_defaults(func=_cmd_lint_rule)

    p_test = sub.add_parser("test-rule", help="Run rule against Feather/Parquet input")
    p_test.add_argument("rule", type=Path)
    p_test.add_argument("--input", required=True, help="Feather or Parquet telemetry file")
    p_test.add_argument("--config", type=Path, help="JSON rule config")
    p_test.set_defaults(func=_cmd_test_rule)

    p_run = sub.add_parser("run-arrow", help="Run rule and optionally write output table")
    p_run.add_argument("rule", type=Path)
    p_run.add_argument("--input", required=True)
    p_run.add_argument("--config", type=Path)
    p_run.add_argument("--output", help="Feather or Parquet output path")
    p_run.set_defaults(func=_cmd_run_arrow)

    p_pack = sub.add_parser("validate-rule-pack", help="Lint all .py rules in a directory")
    p_pack.add_argument("rules_dir", type=Path)
    p_pack.set_defaults(func=_cmd_validate_rule_pack)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
