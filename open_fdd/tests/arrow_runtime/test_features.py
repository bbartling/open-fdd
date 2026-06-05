from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.features import (
    arrow_equipment_filter,
    arrow_select_columns,
    arrow_site_filter,
    arrow_time_filter,
)


def test_select_and_filters():
    table = pa.table(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
            "site_id": ["s1", "s2"],
            "equipment_id": ["e1", "e2"],
            "zone_temp": [70.0, 80.0],
        }
    )
    sel = arrow_select_columns(table, ["site_id", "zone_temp"])
    assert sel.column_names == ["site_id", "zone_temp"]
    site = arrow_site_filter(table, "s1")
    assert site.num_rows == 1
    equip = arrow_equipment_filter(table, "e2")
    assert equip.num_rows == 1


def test_time_filter():
    table = pa.table(
        {
            "timestamp": pa.array(
                ["2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"],
                type=pa.string(),
            ),
            "v": [1, 2],
        }
    )
    import datetime as dt

    out = arrow_time_filter(table, "timestamp", dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc), None)
    assert out.num_rows >= 1
