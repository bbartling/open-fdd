"""Metadata diff base ref: compare registry to merge-base, not origin/master tip (#1454)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import unit_contract_lib as ucl  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "ci")


def _write_contract_tree(repo: Path, registry: dict, tuning: dict) -> None:
    reg_dir = repo / "sql" / "fdd"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "registry.yaml").write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    (reg_dir / "tuning_catalog.json").write_text(json.dumps(tuning), encoding="utf-8")


def _minimal_registry(*, description: str = "baseline") -> dict:
    return {
        "rules": [
            {
                "rule_id": "FC1",
                "sql_file": "fc1_duct_static.sql",
                "required_roles": ["duct_static"],
                "optional_roles": [],
                "description": description,
                "parameters": {
                    "confirm_min": {"default": 5, "unit": "min"},
                },
            }
        ]
    }


@pytest.fixture
def isolated_contract_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "gitrepo"
    repo.mkdir()
    _init_repo(repo)
    tuning = {"rules": []}
    v1 = _minimal_registry()
    _write_contract_tree(repo, v1, tuning)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "v1")

    v2 = copy.deepcopy(v1)
    v2["rules"][0]["parameters"]["confirm_min"]["kind"] = "seconds"
    _write_contract_tree(repo, v2, tuning)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "v2 master metadata")

    _git(repo, "branch", "feature", "HEAD~1")
    _git(repo, "checkout", "feature")

    monkeypatch.setattr(ucl, "ROOT", repo)
    monkeypatch.setattr(ucl, "REGISTRY", repo / "sql/fdd/registry.yaml")
    monkeypatch.setattr(ucl, "TUNING", repo / "sql/fdd/tuning_catalog.json")
    monkeypatch.setattr(ucl, "ensure_origin_master_ref", lambda: "master")
    return repo


def test_merge_base_is_not_master_tip_when_branch_behind(isolated_contract_repo: Path) -> None:
    master_tip = subprocess.check_output(
        ["git", "rev-parse", "master"],
        cwd=isolated_contract_repo,
        text=True,
    ).strip()
    base = ucl.ensure_metadata_diff_base_ref()
    assert base != master_tip
    feature_tip = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=isolated_contract_repo,
        text=True,
    ).strip()
    assert base == feature_tip


def test_behind_master_without_registry_edits_passes(isolated_contract_repo: Path) -> None:
    ucl.assert_metadata_only_registry_diff()
    ucl.assert_metadata_only_tuning_diff()


def test_branch_non_metadata_registry_edit_fails(isolated_contract_repo: Path) -> None:
    reg_path = isolated_contract_repo / "sql/fdd/registry.yaml"
    doc = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    doc["rules"][0]["description"] = "branch changed non-metadata field"
    reg_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(AssertionError, match="differs from merge-base"):
        ucl.assert_metadata_only_registry_diff()
