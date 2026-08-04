"""AHU ↔ VAV topology helpers (feeds / fedBy) for enrich + data model — no invented links."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.role_map import apply_role_map
from app.site_model import resolve_equipment_type


AHU_SAT_ROLE = "ahu-discharge-air-temp"  # parent AHU discharge copied onto VAV frame for cross-equip rules


def invert_vav_to_ahu(vav_to_ahu: dict[str, str] | None) -> dict[str, list[str]]:
    """AHU id → list of VAV children."""
    out: dict[str, list[str]] = {}
    for vav, ahu in (vav_to_ahu or {}).items():
        if not vav or not ahu:
            continue
        out.setdefault(str(ahu), []).append(str(vav))
    for ahu in out:
        out[ahu] = sorted(out[ahu])
    return out


def enrich_frames_with_ahu_feeds(
    frames: dict[str, pd.DataFrame],
    vav_to_ahu: dict[str, str] | None,
    *,
    role_map: dict[str, Any] | None = None,
) -> list[str]:
    """Copy parent AHU ``sat`` onto each VAV as ``ahu_sat`` when topology + series exist.

    Mutates frames in place. Returns human-readable notes (for tests / report).
    """
    notes: list[str] = []
    if not frames or not vav_to_ahu:
        return notes
    rm = role_map or {}
    for vav_id, ahu_id in vav_to_ahu.items():
        if vav_id not in frames or ahu_id not in frames:
            continue
        vav_df = frames[vav_id]
        ahu_raw = frames[ahu_id]
        ahu_rm = {ahu_id: (rm.get(ahu_id) or ahu_raw.attrs.get("_role_map", {}).get(ahu_id) or {})}
        # Prefer already-mapped sat on AHU frame; else apply role_map
        if "discharge-air-temp" in ahu_raw.columns:
            sat = pd.to_numeric(ahu_raw["discharge-air-temp"], errors="coerce")
        else:
            mapped = apply_role_map(ahu_raw, ahu_id, {**rm, **ahu_rm} if rm else ahu_rm)
            if "discharge-air-temp" not in mapped.columns:
                continue
            sat = pd.to_numeric(mapped["discharge-air-temp"], errors="coerce")
        # Align to VAV index
        sat_aligned = sat.reindex(vav_df.index)
        if sat_aligned.notna().sum() == 0:
            continue
        vav_df[AHU_SAT_ROLE] = sat_aligned
        vav_df.attrs["fed_by"] = ahu_id
        notes.append(f"{vav_id}: fedBy {ahu_id} → column {AHU_SAT_ROLE}")
    return notes


def stamp_feed_attrs(
    frames: dict[str, pd.DataFrame],
    vav_to_ahu: dict[str, str] | None,
) -> None:
    """Set fed_by / feeds attrs on frames from topology (even without sat copy)."""
    children = invert_vav_to_ahu(vav_to_ahu)
    for eq_id, df in frames.items():
        et = resolve_equipment_type(eq_id, df=df)
        if et == "VAV" and vav_to_ahu and eq_id in vav_to_ahu:
            df.attrs["fed_by"] = vav_to_ahu[eq_id]
        if et in {"AHU", "RTU"} and eq_id in children:
            df.attrs["feeds"] = list(children[eq_id])
