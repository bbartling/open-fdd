#!/usr/bin/env python3
"""Offline tie fixture for scripts/ghcr_newest_by_created.py (no network)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "ghcr_newest_by_created",
    Path(__file__).resolve().parent / "ghcr_newest_by_created.py",
)
assert _SPEC and _SPEC.loader
ghcr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ghcr)

NEW = "2026-10-26T14:00:00Z"
OLD = "2026-10-25T14:00:00Z"


def row(tag: str, digest: str, created: str) -> dict:
    return {
        "created": created,
        "tag": tag,
        "digest": digest,
        "revision": "",
        "image": f"ghcr.io/bbartling/openfdd-central:{tag}",
    }


class PickNewestTest(unittest.TestCase):
    def test_tie_on_digest_prefers_sha_tag(self) -> None:
        rows = [
            row("nightly", "sha256:new", NEW),
            row("latest", "sha256:new", NEW),
            row("sha-abc1234", "sha256:new", NEW),
            row("sha-0ld0000", "sha256:old", OLD),
        ]
        top, ordered = ghcr.pick_newest(rows)
        self.assertEqual(top["tag"], "sha-abc1234")
        self.assertEqual(top["digest"], "sha256:new")
        self.assertEqual(top["image"], "ghcr.io/bbartling/openfdd-central:sha-abc1234")
        self.assertEqual(len(ordered), 4)
        self.assertEqual(ordered[-1]["tag"], "sha-0ld0000")

    def test_no_sha_tag_falls_back_to_first_tag(self) -> None:
        rows = [
            row("nightly", "sha256:new", NEW),
            row("latest", "sha256:new", NEW),
            row("sha-0ld0000", "sha256:old", OLD),
        ]
        top, _ = ghcr.pick_newest(rows)
        self.assertEqual(top["tag"], "nightly")

    def test_older_sha_tag_on_other_digest_is_not_picked(self) -> None:
        rows = [
            row("sha-0ld0000", "sha256:old", OLD),
            row("nightly", "sha256:new", NEW),
        ]
        top, _ = ghcr.pick_newest(rows)
        self.assertEqual(top["tag"], "nightly")
        self.assertEqual(top["digest"], "sha256:new")

    def test_empty_rows_raise(self) -> None:
        with self.assertRaises(ValueError):
            ghcr.pick_newest([])


if __name__ == "__main__":
    unittest.main()
