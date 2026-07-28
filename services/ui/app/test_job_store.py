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
    meta = job_store.create_job("Bench AHU study", site_name="demo-site", site_id="site-1", ws=ws)
    assert meta.job_id.startswith("job-")
    assert meta.meta_revision
    assert (job_store.job_dir(meta.job_id, ws) / "job.json").is_file()
    for name in ("mapping", "configs", "datasets", "runs", "findings", "reports", "wattlab", "artifacts"):
        assert (job_store.job_dir(meta.job_id, ws) / name).is_dir()
    assert (job_store.job_dir(meta.job_id, ws) / "datasets" / "dataset_refs.json").is_file()

    loaded = job_store.load_job(meta.job_id, ws=ws)
    assert loaded.job_name == "Bench AHU study"
    assert loaded.site_name == "demo-site"
    assert loaded.site_id == "site-1"
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


def test_archive_restore_and_rename(ws: Path) -> None:
    meta = job_store.create_job("Old name", ws=ws)
    renamed = job_store.rename_job(meta.job_id, "New name", ws=ws)
    assert renamed.job_name == "New name"
    archived = job_store.archive_job(meta.job_id, ws=ws)
    assert archived.status == "archived"
    assert archived.archived is True
    assert job_store.list_jobs(ws=ws, include_archived=False) == []
    assert len(job_store.list_jobs(ws=ws, status="archived")) == 1
    restored = job_store.restore_job(meta.job_id, ws=ws)
    assert restored.status == "active"
    assert restored.archived is False


def test_duplicate_copies_mapping_not_runs(ws: Path) -> None:
    meta = job_store.create_job("Src", tags=["rcx"], ws=ws)
    job_store.save_mapping(meta.job_id, {"AHU-1": {"fan_status": "BV:1"}}, ws=ws)
    runs = job_store.job_dir(meta.job_id, ws) / "runs" / "should-not-copy.txt"
    runs.write_text("x", encoding="utf-8")
    copy = job_store.duplicate_job(meta.job_id, new_name="Copy", ws=ws)
    assert copy.job_id != meta.job_id
    assert copy.job_name == "Copy"
    assert job_store.load_mapping(copy.job_id, ws=ws) == {"AHU-1": {"fan_status": "BV:1"}}
    assert not (job_store.job_dir(copy.job_id, ws) / "runs" / "should-not-copy.txt").exists()


def test_revision_conflict(ws: Path) -> None:
    meta = job_store.create_job("Rev", ws=ws)
    stale = meta.meta_revision
    # Concurrent update
    job_store.rename_job(meta.job_id, "Rev2", ws=ws)
    meta.job_name = "Stale write"
    with pytest.raises(job_store.RevisionConflict):
        job_store.save_job(meta, ws=ws, expected_meta_revision=stale)


def test_dataset_refs_roundtrip(ws: Path) -> None:
    meta = job_store.create_job("Data", ws=ws)
    refs = {
        "schema_version": "1",
        "datasets": [
            {
                "dataset_id": "dataset-1",
                "storage_uri": "workspace://data/feather/ahu1",
                "content_hash": "abc",
            }
        ],
    }
    job_store.save_dataset_refs(meta.job_id, refs, dataset_revision="ds-1", ws=ws)
    assert job_store.load_dataset_refs(meta.job_id, ws=ws)["datasets"][0]["content_hash"] == "abc"
    again = job_store.load_job(meta.job_id, ws=ws)
    assert again.revisions.dataset == "ds-1"


def test_corrupt_job_skipped_in_list(ws: Path) -> None:
    good = job_store.create_job("Good", ws=ws)
    bad_id = job_store.new_job_id()
    bad_dir = job_store.jobs_root(ws) / bad_id
    bad_dir.mkdir()
    (bad_dir / "job.json").write_text("{not-json", encoding="utf-8")
    listed = job_store.list_jobs(ws=ws)
    assert [m.job_id for m in listed] == [good.job_id]


def test_malformed_job_json_raises(ws: Path) -> None:
    meta = job_store.create_job("Broken", ws=ws)
    path = job_store.job_dir(meta.job_id, ws) / "job.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        job_store.load_job(meta.job_id, ws=ws)


def test_invalid_schema_and_id(ws: Path) -> None:
    with pytest.raises(ValueError, match="invalid job_id"):
        job_store.job_dir("not-a-job", ws=ws)
    with pytest.raises(ValueError, match="invalid job_id"):
        job_store.job_dir("job-../../../etc", ws=ws)
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
    expected = meta.meta_revision
    meta.job_name = "Atomic2"
    job_store.save_job(meta, ws=ws, expected_meta_revision=expected)
    after = path.read_text(encoding="utf-8")
    assert "Atomic2" in after
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
    expected = meta.meta_revision
    meta.mapping_path = "mapping/role_map.json"
    job_store.save_job(meta, ws=ws, expected_meta_revision=expected)
    with pytest.raises(FileNotFoundError, match="mapping missing"):
        job_store.load_mapping(meta.job_id, ws=ws)


def test_list_filter_by_tag_and_site(ws: Path) -> None:
    job_store.create_job("A", tags=["alpha"], site_id="s1", ws=ws)
    job_store.create_job("B", tags=["beta"], site_id="s2", ws=ws)
    assert len(job_store.list_jobs(ws=ws, tag="alpha")) == 1
    assert len(job_store.list_jobs(ws=ws, site_id="s2")) == 1


def test_findings_dispositions_and_wattlab(ws: Path) -> None:
    meta = job_store.create_job("Findings", ws=ws)
    findings = {
        "schema_version": "1",
        "findings": [
            {
                "finding_id": "finding-1",
                "correlation_key": "rule:VAV-1:equip:AHU-1",
                "run_id": "run-1",
                "evidence": {"sql_row_hash": "abc123"},
            }
        ],
    }
    updated = job_store.save_findings(meta.job_id, findings, findings_revision="f-rev-1", ws=ws)
    assert updated.latest_findings_revision == "f-rev-1"
    loaded = job_store.load_findings(meta.job_id, ws=ws)
    assert loaded["findings"][0]["evidence"]["sql_row_hash"] == "abc123"

    dispositions = {
        "schema_version": "1",
        "dispositions": [
            {
                "correlation_key": "rule:VAV-1:equip:AHU-1",
                "status": "confirmed",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    job_store.save_dispositions(meta.job_id, dispositions, ws=ws)
    assert job_store.load_dispositions(meta.job_id, ws=ws)["dispositions"][0]["status"] == "confirmed"

    handoff_path = job_store.save_wattlab_handoff(
        meta.job_id,
        {"portable_zip_uri": "workspace://exports/demo.zip"},
        ws=ws,
    )
    assert handoff_path.is_file()
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert payload["job_id"] == meta.job_id
    assert payload["portable_zip_uri"] == "workspace://exports/demo.zip"
