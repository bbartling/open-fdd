"""pytest wrapper for openfdd_site_lib.sh / backup / update shell helpers."""

from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LIB = REPO / "scripts" / "openfdd_site_lib.sh"
BASH_TEST = REPO / "tests" / "scripts" / "test_openfdd_site_backup.sh"


def _run_lib(snippet: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = f'{_source_lib()}\n{snippet}'
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        check=False,
    )


def _source_lib() -> str:
    return f'set -euo pipefail; source "{LIB}"'


@pytest.mark.parametrize("script", [LIB, REPO / "scripts" / "openfdd_site_backup.sh", REPO / "scripts" / "openfdd_site_update.sh"])
def test_site_scripts_exist(script: Path) -> None:
    assert script.is_file(), f"missing {script}"


def test_bash_contract_test_passes() -> None:
    proc = subprocess.run(["bash", str(BASH_TEST)], cwd=REPO, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_validate_backup_archive_rejects_missing() -> None:
    proc = _run_lib("openfdd_validate_backup_archive /tmp/no-such-openfdd-backup.tgz")
    assert proc.returncode != 0
    assert "not found" in proc.stderr


def test_validate_backup_archive_accepts_minimal_workspace_tgz(tmp_path: Path) -> None:
    ws = tmp_path / "workspace" / "data"
    ws.mkdir(parents=True)
    (ws / "marker.txt").write_text("ok", encoding="utf-8")
    archive = tmp_path / "workspace-full.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(tmp_path / "workspace", arcname="workspace")

    proc = _run_lib(f'openfdd_validate_backup_archive "{archive}"')
    assert proc.returncode == 0, proc.stderr
    assert "Backup archive OK" in proc.stdout


def test_purge_backup_dir_removes_directory(tmp_path: Path) -> None:
    backup = tmp_path / "latest"
    backup.mkdir()
    (backup / "workspace-full.tgz").write_bytes(b"x")

    proc = _run_lib(f'openfdd_purge_backup_dir "{backup}"')
    assert proc.returncode == 0, proc.stderr
    assert not backup.exists()
    assert "Backup removed" in proc.stdout


def test_feather_restore_cap_drops_oldest_shards(tmp_path: Path) -> None:
    feather = tmp_path / "feather_store" / "bacnet" / "demo"
    feather.mkdir(parents=True)
    for i in range(3):
        (feather / f"shard-1000{i}-x.feather").write_bytes(b"\0" * (2 * 1024 * 1024))

    proc = _run_lib(f'openfdd_apply_feather_restore_cap "{tmp_path / "feather_store"}" 0.003')
    assert proc.returncode == 0, proc.stderr
    remaining = list(feather.glob("shard-*.feather"))
    assert len(remaining) < 3
