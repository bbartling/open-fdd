"""MQTTS gap-blame scorecard (no network)."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mqtts_gap_blame",
    ROOT / "scripts/nightly-ot-bench/mqtts_gap_blame.py",
)
blame = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(blame)


def _layer(**kwargs):
    base = {
        "present": True,
        "samples": 288,
        "max_gap_secs": 300,
        "value_changes": 4,
        "heartbeat_ok": True,
        "published": True,
        "missing_probe": None,
    }
    base.update(kwargs)
    return base


def _io(edge, transit, railway, io_id="RTU_01/sat"):
    return {
        "io_id": io_id,
        "equipment_id": "RTU_01",
        "equipment_type": "ahu",
        "role": "sat",
        "edge": edge,
        "transit": transit,
        "railway": railway,
    }


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.kwargs = {"interval": 300.0, "expected": 288}

    def test_edge_when_publish_never_leaves(self):
        verdict = blame.classify_io(
            _io(_layer(samples=10, max_gap_secs=8000), _layer(samples=10), _layer(samples=10)),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "EDGE")
        self.assertIn("edge", verdict["reason"].lower())

    def test_transit_when_edge_published_and_broker_missed(self):
        verdict = blame.classify_io(
            _io(
                _layer(samples=280),
                _layer(samples=40, max_gap_secs=9000),
                _layer(samples=40, max_gap_secs=9000),
            ),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "TRANSIT")

    def test_railway_when_ingress_kept_and_historian_gapped(self):
        verdict = blame.classify_io(
            _io(
                _layer(samples=280),
                _layer(samples=270),
                _layer(samples=30, max_gap_secs=9000),
            ),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "RAILWAY")
        self.assertIn("historian", verdict["reason"].lower())

    def test_sparse_ok_flat_pv_is_not_loss(self):
        verdict = blame.classify_io(
            _io(
                _layer(value_changes=0, heartbeat_ok=True),
                _layer(value_changes=0),
                _layer(value_changes=0),
            ),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "SPARSE_OK")
        self.assertIn("unchanged", verdict["reason"].lower())

    def test_sparse_ok_agreed_omit(self):
        verdict = blame.classify_io(
            _io(
                _layer(
                    samples=0,
                    max_gap_secs=None,
                    published=False,
                    heartbeat_ok=True,
                    value_unchanged=True,
                    omit_reason="health_roles_only",
                ),
                _layer(samples=0, max_gap_secs=None),
                _layer(samples=0, max_gap_secs=None, value_changes=0),
            ),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "SPARSE_OK")
        self.assertIn("health", verdict["reason"].lower())

    def test_inconclusive_names_missing_mqtt_probe(self):
        verdict = blame.classify_io(
            _io(
                _layer(samples=280),
                blame.layer_absent("mqtt_monitor", blame.TRANSIT_PROBE),
                _layer(samples=20, max_gap_secs=9000),
            ),
            **self.kwargs,
        )
        self.assertEqual(verdict["blame"], "INCONCLUSIVE")
        self.assertIn("mqtt", verdict["reason"].lower())
        self.assertIn("/api/mqtt/monitor", verdict["reason"])

    def test_ok_when_layers_agree(self):
        verdict = blame.classify_io(_io(_layer(), _layer(), _layer()), **self.kwargs)
        self.assertEqual(verdict["blame"], "OK")


class SnapshotTests(unittest.TestCase):
    def test_stale_poll_is_edge(self):
        verdict = blame.classify_snapshot(
            {"edge_poll_age_secs": 9000, "mqtt_age_secs": 9000, "ingest_age_secs": 9000},
            interval=300,
        )
        self.assertEqual(verdict["blame"], "EDGE")

    def test_broker_ack_without_central_is_railway(self):
        verdict = blame.classify_snapshot(
            {
                "edge_poll_age_secs": 10,
                "edge_ack_age_secs": 20,
                "mqtt_age_secs": 9000,
                "ingest_age_secs": 9000,
            },
            interval=300,
        )
        self.assertEqual(verdict["blame"], "RAILWAY")

    def test_failed_publish_and_quiet_cloud_is_transit(self):
        verdict = blame.classify_snapshot(
            {
                "edge_poll_age_secs": 10,
                "edge_ack_age_secs": None,
                "publish_failed": True,
                "mqtt_age_secs": 9000,
            },
            interval=300,
        )
        self.assertEqual(verdict["blame"], "TRANSIT")

    def test_fresh_poll_without_ledger_is_inconclusive(self):
        verdict = blame.classify_snapshot(
            {"edge_poll_age_secs": 10, "mqtt_age_secs": 9000},
            interval=300,
        )
        self.assertEqual(verdict["blame"], "INCONCLUSIVE")
        self.assertIn("publish-ledger", verdict["reason"])

    def test_monitor_fresh_ingest_stale_is_railway(self):
        verdict = blame.classify_snapshot(
            {"mqtt_age_secs": 15, "ingest_age_secs": 4000, "edge_poll_age_secs": 15},
            interval=300,
        )
        self.assertEqual(verdict["blame"], "RAILWAY")


class SelectionAndInspectTests(unittest.TestCase):
    def test_selects_by_equipment_type_not_name_pattern(self):
        rows = [
            {"equipment_id": "CHILLER_1", "equipment_type": "chiller"},
            {"equipment_id": "RTU_FOO_NOT_TYPED", "equipment_type": "GENERAL"},
            {"equipment_id": "AHU_9", "equipment_type": "AHU", "equipment_type_raw": "ahu"},
            {"equipment_id": "RTU_01", "equipment_type": "AHU", "equipment_type_raw": "rtu"},
            {"equipment_id": "VAV_14", "equipment_type": "VAV", "equipment_type_raw": "vav"},
        ]
        chosen = blame.select_samples(rows)
        ids = [item["equipment_id"] for item in chosen]
        self.assertEqual(ids, ["AHU_9", "VAV_14"])
        self.assertNotIn("RTU_FOO_NOT_TYPED", ids)
        preferred = blame.select_samples(rows, prefer_ids=("RTU_01",))
        self.assertEqual(
            [item["equipment_id"] for item in preferred],
            ["RTU_01", "VAV_14"],
        )

    def test_fixture_ids_only_when_type_selection_is_empty(self):
        rows = [
            {"equipment_id": "RTU_01", "equipment_type": "GENERAL"},
            {"equipment_id": "OTHER", "equipment_type": "GENERAL"},
        ]
        self.assertEqual(blame.select_samples(rows), [])
        chosen = blame.select_samples(rows, fixture_ids=("RTU_01", "MISSING"))
        self.assertEqual([item["equipment_id"] for item in chosen], ["RTU_01"])

    def test_coarse_inspect_spacing_is_not_a_railway_gap(self):
        start = datetime(2026, 9, 28, tzinfo=timezone.utc)
        points = []
        for i in range(10):
            ts = start + timedelta(seconds=3600 * i)
            points.append({"timestamp_utc": ts.isoformat(), "sat": 70})
        layer = blame.railway_layer_from_points(
            points,
            role="sat",
            start=start,
            end=start + timedelta(hours=24),
            interval_secs=300,
        )
        self.assertFalse(layer["present"])
        self.assertIn("median spacing", layer["missing_probe"])

    def test_scorecard_lists_counts_and_next_action(self):
        row = _io(_layer(samples=12, max_gap_secs=5000), _layer(samples=12), _layer(samples=12))
        verdict = blame.classify_io(row, interval=300, expected=288)
        report = blame.assemble_report(
            rows=[{**row, **verdict}],
            snapshot=blame.classify_snapshot(
                {"edge_poll_age_secs": 10, "mqtt_age_secs": 10, "ingest_age_secs": 10, "edge_ack_age_secs": 10},
                interval=300,
            ),
            window_hours=24,
            interval_secs=300,
            building_id="ACME",
            edge_id="vim-1",
        )
        text = blame.render_scorecard(report)
        self.assertIn("EDGE=1", text)
        self.assertIn("RTU_01/sat", text)
        self.assertIn("next:", text)
        self.assertEqual(blame.exit_code(report), 1)

    def test_monitor_match_requires_exact_equipment_id(self):
        start = datetime(2026, 9, 28, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)

        def msg(minutes: int, preview: str, topic: str = "openfdd/site/telemetry/bacnet"):
            return {
                "received_at_utc": (start + timedelta(minutes=minutes)).isoformat(),
                "topic": topic,
                "payload_preview": preview,
            }

        longer_id = '{"equipment_id":"RTU_010","role":"sat"}'
        monitor = {
            "recent_messages": [msg(0, longer_id), msg(30, longer_id), msg(90, longer_id)]
        }
        layer = blame.transit_window_from_monitor(
            monitor, equipment_id="RTU_01", start=start, end=end
        )
        self.assertFalse(layer["present"])
        exact = '{"equipment_id": "RTU_01", "role": "sat"}'
        monitor["recent_messages"].extend([msg(0, exact), msg(90, exact)])
        layer = blame.transit_window_from_monitor(
            monitor, equipment_id="RTU_01", start=start, end=end
        )
        self.assertTrue(layer["present"])
        self.assertFalse(blame._text_names_equipment("RTU_010", "RTU_01"))
        self.assertTrue(
            blame._text_names_equipment("openfdd/ACME/RTU_01/telemetry", "RTU_01")
        )


if __name__ == "__main__":
    unittest.main()
