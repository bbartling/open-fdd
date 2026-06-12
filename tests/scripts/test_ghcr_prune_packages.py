"""Unit tests for GHCR prune classification (no live API)."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.ghcr_prune_packages import (
    REASON_DELETE_OLD_RELEASE,
    REASON_DELETE_SHA,
    REASON_DELETE_UNTAGGED,
    REASON_KEEP_ACME_CURRENT,
    REASON_KEEP_LATEST_EDGE,
    REASON_KEEP_PROTECTED,
    REASON_KEEP_RELEASE_WINDOW,
    classify_versions,
    load_protected_tags,
)


def _ver(vid: int, tags: list[str], *, days_ago: int = 1) -> dict:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "id": vid,
        "created_at": ts,
        "updated_at": ts,
        "metadata": {"container": {"tags": tags}},
    }


def test_protected_tags_loaded(tmp_path):
    p = tmp_path / "tags.txt"
    p.write_text("latest\n# comment\nv3.0.31\n", encoding="utf-8")
    assert load_protected_tags(p) == {"latest", "v3.0.31"}


def test_keep_latest_and_protected():
    versions = [_ver(1, ["latest"]), _ver(2, ["v3.0.31"])]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected={"v3.0.31"},
        keep_releases=5,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="",
        previous_acme_tag="",
    )
    assert all(p.action == "keep" for p in plans)
    reasons = {p.reason for p in plans}
    assert REASON_KEEP_LATEST_EDGE in reasons
    assert REASON_KEEP_PROTECTED in reasons


def test_keep_latest_five_releases():
    versions = [
        _ver(i, [f"v3.0.{i}"]) for i in range(10, 0, -1)
    ]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected=set(),
        keep_releases=5,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="",
        previous_acme_tag="",
    )
    kept = [p for p in plans if p.action == "keep" and p.tags[0].startswith("v3.0.")]
    deleted = [p for p in plans if p.action == "delete"]
    assert len(kept) == 5
    assert len(deleted) == 5
    assert all(p.reason == REASON_DELETE_OLD_RELEASE for p in deleted)


def test_keep_current_acme_tag():
    versions = [_ver(1, ["v3.0.5"])]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected=set(),
        keep_releases=1,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="v3.0.5",
        previous_acme_tag="",
    )
    assert plans[0].action == "keep"
    assert plans[0].reason == REASON_KEEP_ACME_CURRENT


def test_delete_untagged_old():
    old = datetime.now(timezone.utc).replace(microsecond=0)
    created = (old.replace(year=old.year - 1)).isoformat().replace("+00:00", "Z")
    versions = [{"id": 99, "created_at": created, "updated_at": created, "metadata": {"container": {"tags": []}}}]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected=set(),
        keep_releases=5,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="",
        previous_acme_tag="",
        now=datetime.now(timezone.utc),
    )
    assert plans[0].action == "delete"
    assert plans[0].reason == REASON_DELETE_UNTAGGED


def test_delete_sha_old():
    old = datetime.now(timezone.utc).replace(microsecond=0)
    created = (old.replace(year=old.year - 1)).isoformat().replace("+00:00", "Z")
    versions = [
        {
            "id": 42,
            "created_at": created,
            "updated_at": created,
            "metadata": {"container": {"tags": ["sha-abc123def456"]}},
        }
    ]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected=set(),
        keep_releases=5,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="",
        previous_acme_tag="",
        now=datetime.now(timezone.utc),
    )
    assert plans[0].action == "delete"
    assert plans[0].reason == REASON_DELETE_SHA


def test_keep_release_window_reason():
    versions = [_ver(1, ["v3.0.32"])]
    plans = classify_versions(
        "openfdd-bridge",
        versions,
        protected=set(),
        keep_releases=5,
        delete_untagged_days=7,
        delete_sha_days=30,
        delete_dev_days=30,
        current_acme_tag="",
        previous_acme_tag="",
    )
    assert plans[0].reason == REASON_KEEP_RELEASE_WINDOW
