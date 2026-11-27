"""Build a device folder (``history_wide.csv`` + ``column_map.json``) for the PyPI tools (#1652).

The folder is what ``open-fdd-ml detect``, ``open-fdd-anomaly screen`` and ``open-fdd-anomaly report`` read:

- ``history_wide.csv``: one row per sample. A ``timestamp_utc`` column (ISO 8601, UTC) and one column per point.
  Values are SI: degC, Pa, fractions 0-1 for commands and positions (0-100 % also works for commands), 0/1 for status.
- ``column_map.json``: ``{"equipType": "AHU", "points": {"<role>": "<column>"}}``. A role is a 223P name
  (``discharge_air_temperature``). A legacy key (``sat``) or the older hyphenated column
  (``discharge-air-temp``) still maps. ``open-fdd-ml make-folder --list-roles`` prints the role names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def role_names() -> dict[str, str]:
    """``{legacy key: 223P role}``. A role with no legacy key is keyed by its own name."""
    from open_fdd.point_roles import load_vocabulary

    names: dict[str, str] = {}
    for rec in load_vocabulary()["roles"]:
        role = str(rec["role"])
        keys = [str(k) for k in (rec.get("legacy_keys") or [])]
        if keys:
            for key in keys:
                names[key] = role
        else:
            names[role] = role
    return dict(sorted(names.items()))


def known_roles() -> set[str]:
    """Role names, legacy keys, aliases and the hyphenated pandas columns."""
    from open_fdd.point_roles import accepted_names

    return accepted_names() | {"run-proof", "pump-status", "return-fan-cmd"}


def write_folder(frame: pd.DataFrame, out: Path | str, points: dict[str, str], *, equip_type: str = "AHU") -> Path:
    """Write ``frame`` (UTC DatetimeIndex, one column per point) and its role map as a device folder."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("the frame needs a DatetimeIndex")
    index = frame.index if frame.index.tz is not None else frame.index.tz_localize("UTC")
    hist = frame.copy()
    hist.index = index.tz_convert("UTC")
    hist = hist[sorted(set(points.values()), key=list(frame.columns).index)]
    hist.insert(0, "timestamp_utc", hist.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    hist.to_csv(out / "history_wide.csv", index=False)
    (out / "column_map.json").write_text(
        json.dumps({"equipType": equip_type, "points": dict(points)}, indent=1), encoding="utf-8"
    )
    return out


def _window(frame: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        frame = frame[frame.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        frame = frame[frame.index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    if frame.empty:
        raise ValueError("no rows left in the --from/--to window")
    return frame


def folder_from_csv(
    csv: Path | str,
    out: Path | str,
    *,
    mapping: dict[str, str],
    time_col: str = "timestamp_utc",
    tz: str = "UTC",
    equip_type: str = "AHU",
    start: str | None = None,
    end: str | None = None,
) -> tuple[Path, list[str]]:
    """A device folder from any wide CSV; returns ``(folder, warnings)``. Naive stamps are read in ``tz``."""
    raw = pd.read_csv(csv)
    if time_col not in raw.columns:
        raise ValueError(f"{csv}: no time column {time_col!r}; pass --time-col (columns: {', '.join(raw.columns[:12])})")
    if not mapping:
        raise ValueError("pass at least one --map ROLE=COLUMN")
    missing = [col for col in mapping.values() if col not in raw.columns]
    if missing:
        raise ValueError(f"{csv}: no column(s) {', '.join(missing)}")
    stamps = pd.to_datetime(raw.pop(time_col), format="mixed")
    stamps = stamps.dt.tz_localize(tz) if stamps.dt.tz is None else stamps
    raw.index = pd.DatetimeIndex(stamps).tz_convert("UTC")
    raw = raw.sort_index()
    warnings = [f"unknown role {role!r} (see --list-roles)" for role in mapping if role not in known_roles()]
    folder = write_folder(_window(raw, start, end), out, mapping, equip_type=equip_type)
    return folder, warnings


def folder_from_lbnl(
    path: Path | str, out: Path | str, *, start: str | None = None, end: str | None = None
) -> Path:
    """A device folder from one LBNL SDAHU CSV (from ``open-fdd-ml download``), already mapped to SI roles."""
    from open_fdd.ml.lbnl import load_sdahu_csv

    frame = _window(load_sdahu_csv(path), start, end)
    renamed = frame.rename(columns=lambda c: str(c).replace("-", "_"))
    points = {str(role): str(role).replace("-", "_") for role in frame.columns}
    return write_folder(renamed, out, points, equip_type="AHU")


def example_folder(out: Path | str, *, days: int = 2, seed: int = 0) -> Path:
    """A tiny synthetic AHU folder (5-minute samples) to try the tools on."""
    import numpy as np

    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=days * 288, freq="5min", tz="UTC")
    hour = idx.hour + idx.minute / 60.0
    on = ((hour >= 6) & (hour < 18)).astype(float)
    frame = pd.DataFrame(
        {
            "SAT": 13 + rng.normal(0, 0.3, len(idx)),
            "MAT": 18 + rng.normal(0, 0.5, len(idx)),
            "RAT": 22 + rng.normal(0, 0.3, len(idx)),
            "OAT": 5 + 4 * np.sin((hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, len(idx)),
            "FAN": on,
        },
        index=idx,
    )
    points = {"discharge_air_temperature": "SAT", "mixed_air_temperature": "MAT",
              "return_air_temperature": "RAT", "outdoor_air_intake_temperature": "OAT",
              "supply_fan_operating_status": "FAN"}
    return write_folder(frame, out, points, equip_type="AHU")
