from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge import bacnet_poll_ingest as ingest  # noqa: E402


def test_tail_csv_reads_header_and_recent_rows(tmp_path: Path):
    path = tmp_path / "samples.csv"
    lines = ["timestamp_utc,point_id,value,site_id"]
    for i in range(50):
        lines.append(f"2026-01-01T00:{i:02d}:00Z,p{i},{i},acme")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = ingest._tail_csv_lines(path, max_data_rows=5)
    assert out[0].startswith("timestamp_utc")
    assert len(out) == 6


def test_incremental_skips_when_no_new_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "samples.csv"
    path.write_text(
        "timestamp_utc,point_id,value,site_id\n2026-06-01T12:00:00Z,p1,1.0,acme\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text('{"last_timestamp_utc": "2026-06-01T12:00:00Z"}', encoding="utf-8")
    monkeypatch.setattr(ingest, "_ingest_state_path", lambda: state_path)
    monkeypatch.setattr(ingest, "bacnet_poll_csv", lambda: path)
    result = ingest.ingest_poll_samples_to_feather(samples_path=path)
    assert result.get("skipped") is True
