from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .codex_launcher import build_invocation, dry_run_command
from .manifest import Manifest
from .tui import run_repl


def _default_repo_root() -> Path:
    return Path.cwd()


def _default_manifest(repo_root: Path) -> Path:
    candidate = repo_root / "openfdd.toml"
    if candidate.is_file():
        return candidate
    return repo_root / "openfdd.toml.example"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "cron":
        from .cron_cli import main as cron_main

        return cron_main(argv[1:])
    if argv and argv[0] == "wake":
        from .wake_cli import main as wake_main

        return wake_main(argv[1:])

    parser = argparse.ArgumentParser(description="Open-FDD skills agent shell")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print Codex command only")
    parser.add_argument("--message", type=str, default=None, help="Single-turn message (non-interactive)")
    args = parser.parse_args(argv)

    repo_root = (args.repo_root or _default_repo_root()).resolve()
    manifest_path = (args.manifest or _default_manifest(repo_root)).resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    manifest = Manifest.load(manifest_path, repo_root)
    manifest.ensure_workspace_dirs()

    if args.message:
        inv = build_invocation(manifest, args.message)
        if args.dry_run:
            print(dry_run_command(inv))
            return 0
        from .tui import codex_available
        from .codex_launcher import run_invocation

        if not codex_available(manifest.codex_bin):
            print(dry_run_command(inv))
            return 1
        return run_invocation(inv)

    return run_repl(manifest, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
