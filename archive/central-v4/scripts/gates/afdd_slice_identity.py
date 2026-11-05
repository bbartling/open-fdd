"""Outside-window identity for gate 38 result slices.

A rows-only rule file fingerprints with null bounds. The lookback upsert
stores those rows on a ``preserved_unscoped`` slice with the same hash.
Gate 38 compares ``(rule_id, start, end, rows_sha256)`` and does not treat
the legacy versus preserved label as a different slice.
"""


def _bound(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def slice_key(rule_id, window):
    """Identity of one result-slice fingerprint.

    Null, missing, and blank bounds collapse to ``None``. Flag bits are not
    part of the key.
    """
    if not isinstance(window, dict):
        window = {}
    return (
        rule_id,
        _bound(window.get("start_utc")),
        _bound(window.get("end_utc")),
        window.get("rows_sha256"),
    )


def _check():
    sha = "8421c728eb5147a66879d36e62be36021653ba33ddb03f798c351193541138dd"
    legacy = {
        "start_utc": None,
        "end_utc": None,
        "preserved_unscoped": False,
        "legacy_unscoped": True,
        "rows_sha256": sha,
    }
    preserved = {
        "start_utc": None,
        "end_utc": None,
        "preserved_unscoped": True,
        "legacy_unscoped": False,
        "rows_sha256": sha,
    }
    null_bound = {
        "start_utc": None,
        "end_utc": None,
        "preserved_unscoped": False,
        "legacy_unscoped": False,
        "rows_sha256": sha,
    }
    blank = {"start_utc": "", "end_utc": "  ", "rows_sha256": sha}
    key = slice_key("FC1", legacy)
    assert key == ("FC1", None, None, sha)
    assert key == slice_key("FC1", preserved)
    assert key == slice_key("FC1", null_bound)
    assert key == slice_key("FC1", blank)
    windowed = slice_key(
        "FC1",
        {
            "start_utc": "2026-09-28T10:00:00Z",
            "end_utc": "2026-09-29T10:00:00Z",
            "preserved_unscoped": False,
            "legacy_unscoped": False,
            "rows_sha256": sha,
        },
    )
    outside = slice_key(
        "FC1",
        {
            "start_utc": "2026-09-01T05:00:00Z",
            "end_utc": "2026-09-02T05:00:00Z",
            "rows_sha256": sha,
        },
    )
    flagged_window = slice_key(
        "FC1",
        {
            "start_utc": "2026-09-01T05:00:00Z",
            "end_utc": "2026-09-02T05:00:00Z",
            "preserved_unscoped": True,
            "rows_sha256": sha,
        },
    )
    assert windowed != key
    assert outside != windowed
    assert flagged_window == outside
    assert slice_key("FC2", preserved) != key
    print("PASS: afdd_slice_identity")


if __name__ == "__main__":
    _check()
