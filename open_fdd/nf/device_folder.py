"""Export one NF equipment's history as an SI device folder (``history_wide.csv`` + ``column_map.json``) (#1653).

The folder is what ``open-fdd-anomaly screen``, ``open-fdd-ml detect`` and ``open-fdd-anomaly report`` read. Values come
from :func:`open_fdd.nf.model.equipment_frames` (NF ``point/data`` resampled to ``window_sec``, roles bound from the
model, units converted to SI with the same plan as the app's ``fdd.js``). Nothing is guessed: a bound point whose unit
cannot be converted stops the export unless the caller allows skips, and every bound point with no unit or an
unrecognised unit is listed in the receipt.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from open_fdd.nf.client import NFClient, NFError, to_iso_z
from open_fdd.nf.model import Model, bind_equipment, equip_pool, equipment_frames, load_model
from open_fdd.nf.units import to_si

#: Skip reasons that mean "this point's unit cannot be turned into SI" (vs. no history in range, text roles).
_UNIT_WORDS = ("unit",)


def _unit_problem(reason: str) -> bool:
    return any(w in reason for w in _UNIT_WORDS)


def resolve_equipment(model: Model, equip: str, site: str | None = None):
    """The single :class:`EquipBinding` matching ``equip`` (id or name), or an :class:`NFError` naming the choices."""
    matches = bind_equipment(model, site=site, equip=equip)
    if not matches:
        raise NFError(f"no equipment matches {equip!r}" + (f" on site {site!r}" if site else "")
                      + " (check `open-fdd-nf model`)")
    if len(matches) > 1:
        where = ", ".join(f"{b.site}/{b.equip}" for b in matches)
        raise NFError(f"{equip!r} matches {len(matches)} equipment ({where}); add --site")
    return matches[0]


def export_folder(client: NFClient, equip: str, start: datetime, end: datetime, out: str | Path, *,
                  site: str | None = None, window_sec: int = 300, allow_skips: bool = False,
                  model: Model | None = None) -> dict[str, Any]:
    """Write ``out/history_wide.csv`` and ``out/column_map.json`` for one equipment; return the receipt dict.

    Raises :class:`NFError` (and writes nothing) when the equipment is ambiguous or missing, has no history in the
    range, or, unless ``allow_skips``, a bound point was dropped because its unit cannot be converted to SI.
    """
    model = model or load_model(client)
    binding = resolve_equipment(model, equip, site)
    frames = equipment_frames(client, model, start, end, window_sec=window_sec, site=binding.site, equip=binding.equip)
    frame = frames.get((binding.site, binding.equip))
    if frame is None or frame.empty:
        raise NFError(f"{binding.site}/{binding.equip}: no history for any bound role between {to_iso_z(start)} and "
                      f"{to_iso_z(end)}")
    skipped: Mapping[str, str] = frame.attrs.get("skipped", {})
    unit_skips = {r: why for r, why in skipped.items() if _unit_problem(why)}
    if unit_skips and not allow_skips:
        detail = "; ".join(f"{r} {why}" for r, why in sorted(unit_skips.items()))
        raise NFError(f"{binding.site}/{binding.equip}: {len(unit_skips)} bound point(s) have a unit that cannot be "
                      f"converted to SI ({detail}). Fix the unit in the model, or pass --allow-skips to export the "
                      "rest and list these in column_map.json")

    bindings: Mapping[str, dict] = frame.attrs.get("bindings", {})
    unit_unverified = {}
    for col, b in bindings.items():
        src = str(b.get("source_unit") or "")
        if b.get("unit") in ("fraction", "bool"):
            continue
        if not src:
            unit_unverified[col] = "no unit on the point; value kept as stored"
        elif to_si(1, src) is None:
            unit_unverified[col] = f'unit "{src}" is not in the SI table; value kept as stored'
    bound_uuids = {b.get("uuid") for b in bindings.values()}
    unmapped = sorted(p.dis or p.uuid for p in equip_pool(binding.equip_rec, model)
                      if p.equip_ref == binding.equip and p.uuid and p.uuid not in bound_uuids)

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wide = frame.copy()
    wide.index = wide.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    wide.index.name = "timestamp_utc"
    wide.to_csv(out_dir / "history_wide.csv", encoding="utf-8")

    columns = list(frame.columns)
    receipt = {
        "source": "open-fdd-nf export-folder",
        "equipType": binding.stamp,
        "equipment_id": binding.equip,
        "equipment_name": binding.dis,
        "site_id": binding.site,
        "start_utc": to_iso_z(start),
        "end_utc": to_iso_z(end),
        "window_sec": window_sec,
        "rows": int(len(frame)),
        "points": {c: c for c in columns},
        "units": {c: frame.attrs.get("role_units", {}).get(c, "") for c in columns},
        "bindings": {c: {k: bindings[c].get(k) for k in ("role", "name", "unit", "source_unit", "class")}
                     for c in columns if c in bindings},
        "skipped": dict(skipped),
        "unit_unverified": unit_unverified,
        "unmapped_points": unmapped,
    }
    (out_dir / "column_map.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt
