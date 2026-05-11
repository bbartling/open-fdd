from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .manifest import Manifest
from .wake.runner import WakeRunner


def _default_repo_root() -> Path:
    return Path.cwd()


def _default_manifest(repo_root: Path) -> Path:
    candidate = repo_root / "openfdd.toml"
    if candidate.is_file():
        return candidate
    return repo_root / "openfdd.toml.example"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description="Open-FDD Codex wake (mini + critique)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mini-invocations", type=int, default=None)
    args = parser.parse_args(argv)

    repo_root = (args.repo_root or _default_repo_root()).resolve()
    manifest_path = (args.manifest or _default_manifest(repo_root)).resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    manifest = Manifest.load(manifest_path, repo_root)
    manifest.ensure_workspace_dirs()
    result = WakeRunner(manifest).run(
        dry_run=args.dry_run,
        mini_count=args.mini_invocations,
    )
    if result.debounced:
        print("wake debounced")
        return 0
    if result.locked:
        print(f"wake locked; see {result.log_path}")
        return 0
    print(f"wake log: {result.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
