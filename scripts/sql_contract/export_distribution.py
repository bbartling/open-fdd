#!/usr/bin/env python3
"""Export a portable SI SQL distribution tree for downstream consumers.

Copies the 110-file scientific ledger plus renderer/tuning companions into ``--out``
(must be outside the git checkout for consumer qualification). Writes
``distribution_manifest.json`` at the artifact root and refreshes the committed
``sql/contract/distribution_manifest.json`` when exporting from a dev checkout.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.sql_contract.companions import COMPANION_RELPATHS  # noqa: E402
from scripts.sql_contract.pack_digest import (  # noqa: E402
    distribution_digest,
    load_scientific_manifest,
    merkle_paths,
    scientific_pack_digest,
    sha256_file,
)

DISTRIBUTION_ID = "openfdd-si-sql-distribution-v1"
DISTRIBUTION_VERSION = "4.0.8-softopen-dist-20261103"
VERIFY_SCRIPT = Path(__file__).resolve().parent / "verify_installed.py"


def _git_head(cwd: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_distribution_doc(*, repo: Path, source_revision: str) -> dict:
    manifest = load_scientific_manifest(repo)
    pack_sha = scientific_pack_digest(manifest)
    companions = []
    for rel in COMPANION_RELPATHS:
        p = repo / rel
        if not p.is_file():
            raise FileNotFoundError(f"missing companion: {rel}")
        companions.append({"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size})
    dist_sha = distribution_digest(scientific_pack_sha256=pack_sha, companion_entries=companions)
    metric = json.loads((repo / "sql/contract/metric_units.json").read_text(encoding="utf-8"))
    unsupported = [str(r.get("rule_id")) for r in metric.get("unsupported_rules") or []]
    return {
        "distribution_id": DISTRIBUTION_ID,
        "distribution_version": DISTRIBUTION_VERSION,
        "processing_abi": manifest.get("processing_abi") or "metric-c-v2",
        "scientific_contract_id": manifest.get("contract_id"),
        "scientific_contract_version": manifest.get("contract_version"),
        "scientific_pack_sha256": pack_sha,
        "scientific_file_count": manifest.get("file_count"),
        "aggregate_digest_definition": {
            "scientific_pack_sha256": (
                "For each path in sql/contract/manifest.json files[] in order: "
                "SHA256.update(path_utf8 + NUL + file_sha256_hex + NUL); final hex digest."
            ),
            "distribution_sha256": (
                "SHA256(scientific_pack_sha256_utf8 + NUL + companion_merkle + NUL); "
                "companion_merkle uses the same per-file update as scientific pack."
            ),
        },
        "distribution_sha256": dist_sha,
        "source_revision": source_revision,
        "companion_files": companions,
        "install_order": {
            "schema_ddl": list(
                __import__(
                    "scripts.sql_contract.companions", fromlist=["SCHEMA_INSTALL_ORDER"]
                ).SCHEMA_INSTALL_ORDER
            ),
            "fdd_helpers": "sql/fdd/postgres/postgres_helpers.sql",
            "fdd_rules": "on-demand via sql/fdd/render_rule.py + sql/fdd/postgres/rules/*.sql",
            "analytics": "on-demand via sql/analytics/postgres/queries/*.sql",
        },
        "client_bindings": {
            "fdd_render": "python3 sql/fdd/render_rule.py <RULE_ID> --dialect postgres --poll-seconds <n>",
            "fdd_execute": "Bind building_id, equipment_id, window; use rendered SQL as parameterized query",
            "analytics_execute": "Load body from registry sql_path; bind per query contract",
            "unit_admission": "sql/contract/metric_units.json source_unit_conversions before SQL",
        },
        "unsupported_rule_ids": unsupported,
        "supported_rule_count": 77,
        "analytics_body_count": 19,
        "verify_entrypoint": "verify_installed.py",
    }


def export_tree(*, repo: Path, out: Path, source_revision: str) -> dict:
    out = out.resolve()
    repo = repo.resolve()
    if out == repo or repo in out.parents or out in repo.parents:
        raise SystemExit("FAIL: --out must be outside the git checkout")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    manifest = load_scientific_manifest(repo)
    for entry in manifest.get("files") or []:
        rel = entry["path"]
        _copy_file(repo / rel, out / rel)
    # Ledger lists equation/schema bytes; manifest.json is the pin document (not in files[]).
    _copy_file(repo / "sql/contract/manifest.json", out / "sql/contract/manifest.json")
    dist_committed = repo / "sql/contract/distribution_manifest.json"
    if dist_committed.is_file():
        _copy_file(dist_committed, out / "sql/contract/distribution_manifest.json")
    for rel in COMPANION_RELPATHS:
        _copy_file(repo / rel, out / rel)

    doc = build_distribution_doc(repo=repo, source_revision=source_revision)
    (out / "distribution_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (out / "SOURCE_REVISION").write_text(source_revision + "\n", encoding="utf-8")
    verify_pkg = Path(__file__).resolve().parent
    shutil.copytree(verify_pkg, out / "_verify" / "sql_contract", dirs_exist_ok=True)
    wrapper = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

art = Path(__file__).resolve().parent
sys.path.insert(0, str(art / "_verify"))
repo = os.environ.get("OPENFDD_VERIFY_REPO")
if repo:
    sys.path.insert(0, repo)
from scripts.sql_contract.verify_installed import main

raise SystemExit(main())
"""
    (out / "verify_installed.py").write_text(wrapper, encoding="utf-8")
    (out / "verify_installed.py").chmod(0o755)
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="Artifact root (outside checkout)")
    p.add_argument("--repo", type=Path, default=ROOT, help="Open-FDD checkout (default: repo root)")
    p.add_argument(
        "--write-committed-manifest",
        action="store_true",
        help="Also write sql/contract/distribution_manifest.json in the repo",
    )
    args = p.parse_args(argv)
    rev = _git_head(args.repo)
    doc = export_tree(repo=args.repo, out=args.out, source_revision=rev)
    if args.write_committed_manifest:
        committed = args.repo / "sql/contract/distribution_manifest.json"
        committed.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out.resolve()), "distribution_sha256": doc["distribution_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
