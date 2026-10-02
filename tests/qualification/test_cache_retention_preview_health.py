"""Acceptance classifiers for cache, retention, series preview, and health hang."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cache_retention_preview_health",
    ROOT / "scripts/qualification/cache_retention_preview_health.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ContractTests(unittest.TestCase):
    def test_nginx_liveness_is_bounded(self) -> None:
        text = (ROOT / "frontend/web/nginx.conf").read_text(encoding="utf-8")
        self.assertEqual(mod.check_nginx(text), [])

    def test_series_preview_is_newest_n(self) -> None:
        ts = (ROOT / "frontend/web/src/components/seriesPreview.ts").read_text(encoding="utf-8")
        tsx = (ROOT / "frontend/web/src/components/SeriesPreview.tsx").read_text(encoding="utf-8")
        self.assertEqual(mod.check_series_preview(ts, tsx), [])

    def test_cache_hit_requires_elapsed_and_does_not_hide_stale(self) -> None:
        ok, detail = mod.cache_pair_ok(
            {"cache": {"hit": False, "elapsed_ms": 40}},
            {"cache": {"hit": True, "elapsed_ms": 3, "stale": False}},
        )
        self.assertTrue(ok, detail)
        bad, why = mod.cache_pair_ok(
            {"cache": {"hit": False, "elapsed_ms": 40}},
            {"stale": True, "cache": {"hit": True, "elapsed_ms": 3, "stale": False}},
        )
        self.assertFalse(bad)
        self.assertIn("stale", why)
        missed, why = mod.cache_pair_ok(
            {"cache": {"hit": False, "elapsed_ms": 10}},
            {"cache": {"hit": False, "elapsed_ms": 10}},
        )
        self.assertFalse(missed)
        self.assertIn("hit", why)

    def test_unload_clears_historian_resident(self) -> None:
        ok, _detail = mod.unload_cleared(
            {"historian_resident": ["site-a"], "ram_resident": ["site-a"]},
            {"historian_resident": [], "ram_resident": []},
            "site-a",
        )
        self.assertTrue(ok)
        stuck, detail = mod.unload_cleared(
            {"historian_resident": ["site-a"]},
            {"historian_resident": ["site-a"]},
            "site-a",
        )
        self.assertFalse(stuck)
        self.assertIn("site-a", detail)

    def test_budget_shape_is_100_gib_oldest_first(self) -> None:
        ok, detail = mod.budget_snapshot_ok(
            {
                "ok": True,
                "enabled": False,
                "budget_gib": 100,
                "default_budget_gib": 100,
                "policy": "oldest-first; newest parquet kept",
            }
        )
        self.assertTrue(ok, detail)
        bad, why = mod.budget_snapshot_ok(
            {"ok": True, "enabled": True, "budget_gib": 5, "default_budget_gib": 5, "policy": "newest"}
        )
        self.assertFalse(bad)
        self.assertTrue("100" in why or "oldest-first" in why)

    def test_blackhole_central_does_not_hang_the_shell(self) -> None:
        result = mod.simulate_central_restart()
        self.assertEqual(mod.check_restart_simulation(result), [], result)


if __name__ == "__main__":
    unittest.main()
