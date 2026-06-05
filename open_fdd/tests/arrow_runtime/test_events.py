from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.events import count_mask_values, detect_fault_episodes


def test_episodes_and_counts():
    table = pa.table({"timestamp": ["t1", "t2", "t3", "t4", "t5"]})
    mask = pa.array([False, True, True, False, True])
    counts = count_mask_values(mask)
    assert counts["true_count"] == 3
    episodes = detect_fault_episodes(table, mask, rule_id="r1")
    assert len(episodes) == 2
    assert episodes[0]["samples"] == 2
