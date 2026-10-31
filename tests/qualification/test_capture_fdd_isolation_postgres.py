import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


def _load_capture():
    spec = importlib.util.spec_from_file_location(
        "capture_iso_pg",
        STRESS / "si_cutover" / "capture_ip_baseline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_parity():
    path = REPO / "scripts" / "timescale" / "test_synthetic_pandas_sql_parity.py"
    spec = importlib.util.spec_from_file_location("ts_parity_iso", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


capture = _load_capture()
parity = _load_parity()


def _insert_fdd_run(
    conn,
    *,
    site_id: str,
    run_id: str,
    created_at: datetime,
) -> None:
    ws = datetime(2026, 6, 1, tzinfo=timezone.utc)
    we = datetime(2026, 6, 2, tzinfo=timezone.utc)
    detail = json.dumps({"run_id": run_id})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fdd_run (
              site_id, equipment_id, rule_id, window_start, window_end,
              poll_seconds, confirm_min, status, detail, created_at
            ) VALUES (%s, %s, %s, %s, %s, 300, 0, 'OK', %s::jsonb, %s)
            """,
            (site_id, "AHU_1", "FC1", ws, we, detail, created_at),
        )
    conn.commit()


@unittest.skipUnless(
    os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    "OPENFDD_DATABASE_URL required for disposable Postgres isolation proof",
)
class CaptureFddIsolationPostgresTests(unittest.TestCase):
    site_id = "CAPTURE_ISO_PG"

    def setUp(self) -> None:
        self.conn = parity.connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])
        parity.apply_schema(self.conn)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM fdd_run WHERE site_id = %s", (self.site_id,))
        self.conn.commit()
        self.base = datetime.now(timezone.utc) - timedelta(hours=2)
        _insert_fdd_run(
            self.conn,
            site_id=self.site_id,
            run_id="capture-allowed-1",
            created_at=self.base,
        )
        self.marker = capture.fdd_run_created_at_marker(self.conn, self.site_id)
        self.allowed = {"capture-allowed-1"}

    def tearDown(self) -> None:
        self.conn.close()

    def test_foreign_run_during_sql_readback_fails(self) -> None:
        original = capture.fetch_sql_daily_rows
        foreign_conn = parity.connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])

        def fetch_with_interleave(_conn, **_kwargs):
            _insert_fdd_run(
                foreign_conn,
                site_id=self.site_id,
                run_id="run-afdd-mid-readback",
                created_at=datetime.now(timezone.utc),
            )
            return []

        try:
            with mock.patch.object(capture, "fetch_sql_daily_rows", side_effect=fetch_with_interleave):
                with self.assertRaises(capture.CaptureQualificationError) as ctx:
                    capture.capture_sql_readback_under_isolation(
                        self.conn,
                        building_id=self.site_id,
                        window_start="2026-06-01T00:00:00Z",
                        window_end="2026-06-02T00:00:00Z",
                        scope_marker=self.marker,
                        allowed_run_ids=self.allowed,
                    )
            self.assertIn("concurrent_non_capture_fdd_run", str(ctx.exception.reason))
        finally:
            foreign_conn.close()

    def test_foreign_run_between_batches_detected_at_next_guard(self) -> None:
        foreign_conn = parity.connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])
        _insert_fdd_run(
            foreign_conn,
            site_id=self.site_id,
            run_id="run-afdd-between-batches",
            created_at=datetime.now(timezone.utc),
        )
        foreign_conn.close()
        with self.assertRaises(capture.CaptureQualificationError):
            capture.assert_no_interleaved_fdd_run(
                self.conn,
                building_id=self.site_id,
                marker=self.marker,
                allowed_run_ids=self.allowed,
            )


if __name__ == "__main__":
    unittest.main()
