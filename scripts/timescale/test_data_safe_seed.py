#!/usr/bin/env python3
"""Arg-free decisions for the lab Timescale seed scripts."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_safe import (  # noqa: E402
    ALREADY_CONSUMED,
    CONSUME_EMPTY,
    COPY_ONLY,
    DELETE_THEN_COPY,
    PRESERVE,
    REFUSE,
    REGISTRY_ONLY,
    RESET,
    env_flag_on,
    purge_decision,
    reset_token,
    seed_action,
)
import purge_historian  # noqa: E402


class SeedDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.get(key)
            for key in ("OPENFDD_RESET_DB", "OPENFDD_ALLOW_DESTRUCTIVE_DB", "OPENFDD_DATABASE_URL")
        }
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    def test_empty_site_copies_without_deleting(self) -> None:
        self.assertEqual(seed_action(False, 0, False, False), COPY_ONLY)
        self.assertEqual(seed_action(False, 0, True, False), COPY_ONLY)

    def test_existing_rows_are_refused_by_default(self) -> None:
        self.assertEqual(seed_action(False, 12, False, False), REFUSE)
        self.assertEqual(seed_action(False, 12, True, False), REFUSE)
        self.assertEqual(seed_action(True, 12, True, False), REFUSE)

    def test_allow_flag_alone_does_not_delete(self) -> None:
        self.assertEqual(seed_action(False, 12, False, True), REFUSE)
        self.assertEqual(seed_action(True, 12, False, True), REGISTRY_ONLY)

    def test_both_flags_are_required_to_delete(self) -> None:
        self.assertEqual(seed_action(False, 12, True, True), DELETE_THEN_COPY)
        self.assertEqual(seed_action(True, 4, True, True), DELETE_THEN_COPY)

    def test_already_seeded_stays_on_registry_refresh(self) -> None:
        self.assertEqual(seed_action(True, 4, False, False), REGISTRY_ONLY)

    def test_env_flag(self) -> None:
        self.assertTrue(env_flag_on("1"))
        self.assertTrue(env_flag_on(" YES "))
        self.assertFalse(env_flag_on(None))
        self.assertFalse(env_flag_on("0"))
        self.assertFalse(env_flag_on("false"))

    def test_reset_token(self) -> None:
        self.assertIsNone(reset_token(None))
        self.assertIsNone(reset_token("0"))
        self.assertIsNone(reset_token(" false "))
        self.assertEqual(reset_token("1"), "1")
        self.assertEqual(reset_token(" b50-wipe-20261020 "), "b50-wipe-20261020")

    def test_purge_requires_token_and_allow_and_is_one_shot(self) -> None:
        self.assertEqual(purge_decision(None, False, None, True), PRESERVE)
        self.assertEqual(purge_decision(None, True, None, True), PRESERVE)
        self.assertEqual(purge_decision("b50-wipe-20261020", False, None, True), REFUSE)
        self.assertEqual(purge_decision("b50-wipe-20261020", True, None, True), RESET)
        self.assertEqual(purge_decision("b50-wipe-20261020", True, None, False), CONSUME_EMPTY)
        self.assertEqual(
            purge_decision("b50-wipe-20261020", True, "b50-wipe-20261020", True),
            ALREADY_CONSUMED,
        )
        self.assertEqual(purge_decision("b50-wipe-again", True, "b50-wipe-20261020", True), RESET)

    def test_purge_script_dry_run_defaults_to_preserve(self) -> None:
        self.assertEqual(purge_historian.main(["--dry-run"]), 0)

    def test_purge_script_refuses_token_without_allow(self) -> None:
        code = purge_historian.main(["--dry-run", "--reset-db", "b50-wipe-20261020"])
        self.assertEqual(code, 2)

    def test_purge_script_acknowledged_dry_run_requests_reset(self) -> None:
        code = purge_historian.main(
            [
                "--dry-run",
                "--reset-db",
                "b50-wipe-20261020",
                "--i-understand-data-loss",
            ]
        )
        self.assertEqual(code, 0)

    def test_purge_table_list_matches_central(self) -> None:
        rust = Path(__file__).resolve().parents[2].joinpath(
            "services/central/src/db_lifecycle.rs"
        )
        text = rust.read_text(encoding="utf-8")
        block = text.split("const RESET_TABLES:", 1)[1].split("];", 1)[0]
        rust_tables = [
            line.strip().strip(",").strip('"')
            for line in block.splitlines()
            if line.strip().startswith('"')
        ]
        self.assertEqual(rust_tables, list(purge_historian.RESET_TABLES))
        self.assertIn("sample", rust_tables)
        self.assertIn("seed_meta", rust_tables)


if __name__ == "__main__":
    unittest.main()
