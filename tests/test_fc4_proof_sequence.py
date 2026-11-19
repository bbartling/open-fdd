"""#1631: pandas FC4 counts operating-state entries over proven samples only (twin of fc4_os_hunting.sql and
nf-app/tests/fc4-proof-sequence.test.mjs): a valve that flaps only across unproven samples is not hunting."""

import pandas as pd

from open_fdd.rules.cookbook_catalog import fc4


def _frame(proof_when):
    idx = pd.date_range("2026-01-01", periods=49, freq="5min", tz="UTC")
    d = pd.DataFrame({
        "fan-status": 1.0,
        "cooling-valve": [0.0 if i % 2 else 0.5 for i in range(49)],
        "heating-valve": 0.0,
        "outside-air-damper": 0.0,
        "run-proof": [1.0 if proof_when(i) else 0.0 for i in range(49)],
    }, index=idx)
    d.attrs["run_proof_resolved"] = True
    return d


def test_proven_hunting_is_flagged():
    assert fc4(_frame(lambda i: True), {}, 300.0).sum() > 24


def test_flapping_only_across_unproven_samples_is_not_counted():
    assert fc4(_frame(lambda i: i % 2 == 0), {}, 300.0).sum() == 0


def test_gate_off_counts_every_sample():
    assert fc4(_frame(lambda i: i % 2 == 0), {"require_run_proof": 0}, 300.0).sum() > 24
