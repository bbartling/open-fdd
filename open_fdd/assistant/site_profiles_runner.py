"""
Load declarative ``site_profiles.yaml`` packs (CSV paths + BRICK mappings) and apply them to the desktop model.

Used by ``scripts/bootstrap_ahu_examples.py`` and by the bridge ``POST /assistant/apply-site-profiles`` helper
so ingest + modeling stay **data-driven**, not tied to specific filenames in Python code.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.paths import default_rules_root


def _assert_path_under(base: Path, target: Path, *, what: str) -> None:
    """Reject symlink/path tricks that escape the profile directory (``base``)."""
    base_r = base.resolve()
    target_r = target.resolve()
    try:
        target_r.relative_to(base_r)
    except ValueError as exc:
        raise ValueError(f"{what} must stay under profile directory {base_r}: got {target_r}") from exc


def _apply_brick_mappings(model: dict[str, Any], *, site_id: str, mappings: list[dict[str, Any]]) -> int:
    by_ext = {str(m["external_id"]).strip(): str(m["brick_type"]).strip() for m in mappings if m.get("external_id")}
    n = 0
    for p in model.get("points", []):
        if not isinstance(p, dict):
            continue
        if str(p.get("site_id")) != str(site_id):
            continue
        ext = str(p.get("external_id") or "").strip()
        if ext not in by_ext:
            continue
        brick = by_ext[ext]
        p["brick_type"] = brick
        p["fdd_input"] = brick
        n += 1
    return n


def load_site_profiles(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"site_profiles: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("site_profiles: root must be a mapping")
    if int(raw.get("version", 1)) != 1:
        raise ValueError("site_profiles: only version: 1 is supported")
    sites = raw.get("sites")
    if not isinstance(sites, list) or not sites:
        raise ValueError("site_profiles: sites must be a non-empty list")
    for idx, site in enumerate(sites):
        if not isinstance(site, dict):
            raise ValueError(f"site_profiles: sites[{idx}] must be a mapping")
        if not str(site.get("display_name") or "").strip():
            raise ValueError(f"site_profiles: sites[{idx}].display_name is required")
        csv_block = site.get("csv")
        if not isinstance(csv_block, dict) or not str(csv_block.get("path") or "").strip():
            raise ValueError(f"site_profiles: sites[{idx}].csv.path is required")
        eq = site.get("equipment")
        if not isinstance(eq, dict) or not str(eq.get("name") or "").strip():
            raise ValueError(f"site_profiles: sites[{idx}].equipment.name is required")
        maps = site.get("brick_mappings")
        if not isinstance(maps, list) or not maps:
            raise ValueError(f"site_profiles: sites[{idx}].brick_mappings must be a non-empty list")
        for j, m in enumerate(maps):
            if not isinstance(m, dict) or not m.get("external_id") or not m.get("brick_type"):
                raise ValueError(f"site_profiles: sites[{idx}].brick_mappings[{j}] needs external_id and brick_type")
    return raw


def apply_site_profiles_file(
    *,
    profiles_yaml: Path,
    model: ModelService,
    ingest: IngestService,
    ttl: TtlService,
    reset: bool,
) -> dict[str, Any]:
    """
    Ingest CSVs, assign equipment, apply BRICK mappings, sync TTL, optionally copy workshop rules into ``ahu_vav``.
    """
    profiles_yaml = profiles_yaml.resolve()
    base = profiles_yaml.parent
    data = load_site_profiles(profiles_yaml)

    if reset:
        ingest.purge_timeseries()
        model.store.save({"sites": [], "equipment": [], "points": []})

    site_summaries: list[dict[str, Any]] = []
    for site_cfg in data["sites"]:
        name = str(site_cfg["display_name"]).strip()
        site = model.create_site(name)
        eq_spec = site_cfg["equipment"]
        eq = model.create_equipment(
            site_id=site["id"],
            name=str(eq_spec["name"]).strip(),
            equipment_type=str(eq_spec.get("type") or "Equipment").strip(),
        )
        csv_block = site_cfg["csv"]
        csv_path = (base / str(csv_block["path"]).strip()).resolve()
        _assert_path_under(base, csv_path, what="CSV path")
        if not csv_path.is_file():
            raise FileNotFoundError(f"CSV not found for site {name!r}: {csv_path}")
        source = str(csv_block.get("source") or "csv").strip() or "csv"
        ing = ingest.ingest_csv(csv_path=str(csv_path), site_id=site["id"], source=source)
        with model.transaction() as m:
            for p in m["points"]:
                if not isinstance(p, dict) or str(p.get("site_id")) != str(site["id"]):
                    continue
                if p.get("equipment_id") is None:
                    p["equipment_id"] = eq["id"]
            _apply_brick_mappings(m, site_id=site["id"], mappings=site_cfg["brick_mappings"])
        ttl.sync()
        site_summaries.append(
            {
                "site_id": site["id"],
                "display_name": name,
                "ingest_rows": int(ing.get("rows", 0) or 0),
                "metrics": len(ing.get("metrics", []) or []),
            },
        )

    copied: list[str] = []
    rules_sub = data.get("copy_rules_from")
    if rules_sub:
        src_dir = (base / str(rules_sub).strip()).resolve()
        _assert_path_under(base, src_dir, what="copy_rules_from directory")
        if not src_dir.is_dir():
            raise FileNotFoundError(f"copy_rules_from not a directory: {src_dir}")
        dest_dir = default_rules_root() / "ahu_vav"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.glob("*.yaml")):
            src_res = src.resolve()
            _assert_path_under(base, src_res, what="copy_rules_from rule file")
            dst = dest_dir / src.name
            shutil.copy2(src_res, dst)
            copied.append(src.name)

    return {"sites": site_summaries, "rules_copied": copied, "profiles_file": str(profiles_yaml)}
