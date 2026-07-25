"""Tests for workspace/jobs Job store (filesystem contract)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import job_store


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_create_list_load_roundtrip(ws: Path) -> None:
    meta = job_store.create_job("Bench AHU study", site_name="demo-site", ws=ws)
    assert meta.job_id.startswith("job-")
    assert (job_store.job_dir(meta.job_id, ws) / "job.json").is_file()
    for name in ("mapping", "configs", "runs", "findings", "reports", "wattlab", "artifacts"):
        assert (job_store.job_dir(meta.job_id, ws) / name).is_dir()

    loaded = job_store.load_job(meta.job_id, ws=ws)
    assert loaded.job_name == "Bench AHU study"
    assert loaded.site_name == "demo-site"
    assert loaded.status == "active"

    listed = job_store.list_jobs(ws=ws)
    assert len(listed) == 1
    assert listed[0].job_id == meta.job_id


def test_save_reopen_restores_mapping(ws: Path) -> None:
    meta = job_store.create_job("Map test", ws=ws)
    mapping = {"AHU-1": {"supply_air_temp": "AV:1", "fan_status": "BV:2"}}
    job_store.save_mapping(meta.job_id, mapping, mapping_revision="map-v1", ws=ws)

    again = job_store.load_job(meta.job_id, ws=ws)
    assert again.revisions.mapping == "map-v1"
    assert again.mapping_path == "mapping/role_map.json"
    assert job_store.load_mapping(meta.job_id, ws=ws) == mapping


def test_archive_and_rename(ws: Path) -> None:
    meta = job_store.create_job("Old name", ws=ws)
    renamed = job_store.rename_job(meta.job_id, "New name", ws=ws)
    assert renamed.job_name == "New name"
    archived = job_store.archive_job(meta.job_id, ws=ws)
    assert archived.status == "archived"
    assert job_store.list_jobs(ws=ws, include_archived=False) == []
    assert len(job_store.list_jobs(ws=ws, include_archived=True)) == 1


def test_malformed_job_json_raises(ws: Path) -> None:
    meta = job_store.create_job("Broken", ws=ws)
    path = job_store.job_dir(meta.job_id, ws) / "job.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        job_store.load_job(meta.job_id, ws=ws)


def test_invalid_schema_and_id(ws: Path) -> None:
    with pytest.raises(ValueError, match="invalid job_id"):
        job_store.job_dir("not-a-job", ws=ws)
    meta = job_store.create_job("ok", ws=ws)
    path = job_store.job_dir(meta.job_id, ws) / "job.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = 99
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        job_store.load_job(meta.job_id, ws=ws)


def test_atomic_write_survives_reader(ws: Path) -> None:
    meta = job_store.create_job("Atomic", ws=ws)
    path = job_store.job_dir(meta.job_id, ws) / "job.json"
    before = path.read_text(encoding="utf-8")
    meta.job_name = "Atomic2"
    job_store.save_job(meta, ws=ws)
    after = path.read_text(encoding="utf-8")
    assert "Atomic2" in after
    # prior content was valid JSON; new content must parse
    json.loads(before)
    json.loads(after)


def test_delete_requires_confirm(ws: Path) -> None:
    meta = job_store.create_job("Doomed", ws=ws)
    with pytest.raises(ValueError, match="confirm"):
        job_store.delete_job(meta.job_id, ws=ws)
    job_store.delete_job(meta.job_id, ws=ws, confirm=True)
    with pytest.raises(FileNotFoundError):
        job_store.load_job(meta.job_id, ws=ws)


def test_missing_mapping_file_raises(ws: Path) -> None:
    meta = job_store.create_job("No map file", ws=ws)
    meta.mapping_path = "mapping/role_map.json"
    job_store.save_job(meta, ws=ws)
    with pytest.raises(FileNotFoundError, match="mapping missing"):
        job_store.load_mapping(meta.job_id, ws=ws)
