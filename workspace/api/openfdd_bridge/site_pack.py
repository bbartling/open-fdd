"""Per-site workspace packs — backup/restore without cross-site contamination."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import commissioning_dir, data_dir, repo_root
from .rule_store import RuleStore
from .model_service import ModelService
from .ttl_service import TtlService

_PACK_FILES = (
    "model.json",
    "rules_store.json",
    "points.csv",
    "points_discovered.csv",
    "commission.env",
    "device_poll_profiles.csv",
)


@dataclass(frozen=True)
class SitePackRef:
    site_id: str
    building_id: str

    @property
    def slug(self) -> str:
        return f"{self.site_id}/{self.building_id}"


def edge_config_dir() -> Path:
    return repo_root() / "edge_config"


def edge_backup_dir() -> Path:
    return repo_root() / "edge_backup" / "local"


def pack_dir(ref: SitePackRef, *, prefer_backup: bool = True) -> Path:
    backup = edge_backup_dir() / ref.site_id / ref.building_id
    if prefer_backup and backup.is_dir() and any((backup / f).is_file() for f in _PACK_FILES):
        return backup
    return edge_config_dir() / ref.site_id / ref.building_id


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_points_csv(path: Path, ref: SitePackRef) -> list[str]:
    import csv

    errors: list[str] = []
    if not path.is_file():
        return errors
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            sid = str(row.get("site_id") or "").strip()
            bid = str(row.get("building_id") or "").strip()
            if sid and sid != ref.site_id:
                errors.append(f"points.csv line {i}: site_id={sid!r} expected {ref.site_id!r}")
            if bid and bid != ref.building_id:
                errors.append(f"points.csv line {i}: building_id={bid!r} expected {ref.building_id!r}")
    return errors


def _validate_model(model: dict[str, Any], ref: SitePackRef) -> list[str]:
    errors: list[str] = []
    site_ids = {str(s.get("id") or "") for s in model.get("sites") or [] if isinstance(s, dict)}
    if ref.site_id not in site_ids:
        errors.append(f"model.json sites missing {ref.site_id!r}: {sorted(site_ids)}")
    for key in ("equipment", "points"):
        for row in model.get(key) or []:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("site_id") or "").strip()
            if sid and sid != ref.site_id:
                errors.append(f"model {key} row {row.get('id')}: site_id={sid!r}")
    return errors


def _validate_rules(rules: list[dict[str, Any]], ref: SitePackRef, *, forbid_prefixes: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "")
        for prefix in forbid_prefixes:
            if rid.startswith(prefix):
                errors.append(f"rule {rid!r} forbidden for site {ref.slug}")
        for pid in rule.get("bindings", {}).get("point_ids", []) or []:
            if isinstance(pid, str) and pid.startswith("acme-") and ref.site_id != "acme":
                errors.append(f"rule {rid} binds acme point {pid!r}")
    return errors


def validate_pack(ref: SitePackRef, pack_root: Path, *, forbid_acme_rules: bool = False) -> list[str]:
    errors: list[str] = []
    model_path = pack_root / "model.json"
    if model_path.is_file():
        errors.extend(_validate_model(_read_json(model_path), ref))
    points_path = pack_root / "points.csv"
    errors.extend(_validate_points_csv(points_path, ref))
    errors.extend(_validate_points_csv(pack_root / "points_discovered.csv", ref))
    profiles = pack_root / "device_poll_profiles.csv"
    if profiles.is_file():
        import csv

        with profiles.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "device_instance" not in (reader.fieldnames or []):
                errors.append("device_poll_profiles.csv missing device_instance column")
    rules_path = pack_root / "rules_store.json"
    if rules_path.is_file():
        raw = _read_json(rules_path)
        rules = raw.get("rules") if isinstance(raw, dict) else []
        prefixes = ("acme-",) if forbid_acme_rules else ()
        errors.extend(_validate_rules(list(rules or []), ref, forbid_prefixes=prefixes))
    return errors


def backup_site(ref: SitePackRef, dest: Path | None = None) -> Path:
    """Copy live workspace BACnet + model + rules into edge_backup/local."""
    dest = dest or pack_dir(ref, prefer_backup=False)
    dest.mkdir(parents=True, exist_ok=True)
    src_model = data_dir() / "model.json"
    src_rules = data_dir() / "rules_store.json"
    src_points = commissioning_dir() / "points.csv"
    src_discovered = commissioning_dir() / "points_discovered.csv"
    src_comm = commissioning_dir() / "commission.env"
    src_profiles = commissioning_dir() / "device_poll_profiles.csv"
    if src_model.is_file():
        shutil.copy2(src_model, dest / "model.json")
    if src_rules.is_file():
        shutil.copy2(src_rules, dest / "rules_store.json")
    if src_points.is_file():
        shutil.copy2(src_points, dest / "points.csv")
    if src_discovered.is_file():
        shutil.copy2(src_discovered, dest / "points_discovered.csv")
    if src_comm.is_file():
        shutil.copy2(src_comm, dest / "commission.env")
    if src_profiles.is_file():
        shutil.copy2(src_profiles, dest / "device_poll_profiles.csv")
    meta = {
        "site_id": ref.site_id,
        "building_id": ref.building_id,
        "backed_up_from": "workspace",
    }
    (dest / "pack_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest


def apply_site(
    ref: SitePackRef,
    *,
    pack_root: Path | None = None,
    forbid_acme_rules: bool | None = None,
    sync_ttl: bool = True,
) -> dict[str, str]:
    """Restore a site pack into workspace/ (model, rules, BACnet CSV, commission.env)."""
    root = pack_root or pack_dir(ref)
    if not root.is_dir():
        raise FileNotFoundError(f"site pack not found: {root}")
    if forbid_acme_rules is None:
        forbid_acme_rules = ref.site_id != "acme"
    errors = validate_pack(ref, root, forbid_acme_rules=forbid_acme_rules)
    if errors:
        raise ValueError("site pack validation failed:\n  " + "\n  ".join(errors))

    applied: dict[str, str] = {}
    model_path = root / "model.json"
    if model_path.is_file():
        shutil.copy2(model_path, data_dir() / "model.json")
        applied["model.json"] = str(data_dir() / "model.json")

    rules_path = root / "rules_store.json"
    if rules_path.is_file():
        shutil.copy2(rules_path, data_dir() / "rules_store.json")
        applied["rules_store.json"] = str(data_dir() / "rules_store.json")

    points_path = root / "points.csv"
    if points_path.is_file():
        dest = commissioning_dir() / "points.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(points_path, dest)
        applied["points.csv"] = str(dest)

    comm_path = root / "commission.env"
    if comm_path.is_file():
        dest = commissioning_dir() / "commission.env"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(comm_path, dest)
        applied["commission.env"] = str(dest)

    disc_path = root / "points_discovered.csv"
    if disc_path.is_file():
        dest = commissioning_dir() / "points_discovered.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(disc_path, dest)
        applied["points_discovered.csv"] = str(dest)

    profiles_path = root / "device_poll_profiles.csv"
    if profiles_path.is_file():
        dest = commissioning_dir() / "device_poll_profiles.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(profiles_path, dest)
        applied["device_poll_profiles.csv"] = str(dest)

    if sync_ttl and applied.get("model.json"):
        TtlService().sync()

    return applied


def purge_foreign_rules(
    *,
    keep_prefixes: tuple[str, ...] = ("bench-", "duct-"),
    store: RuleStore | None = None,
) -> int:
    """Remove rules whose ids do not start with allowed prefixes (bench cleanup)."""
    store = store or RuleStore()
    doc = store.load()
    rules = doc.get("rules") or []
    kept = [r for r in rules if isinstance(r, dict) and any(str(r.get("id", "")).startswith(p) for p in keep_prefixes)]
    removed = len(rules) - len(kept)
    if removed:
        doc["rules"] = kept
        store._save(doc)
    return removed


def site_ref_from_env() -> SitePackRef:
    comm = commissioning_dir() / "commission.env"
    site_id = "demo"
    building_id = "bens-office"
    if comm.is_file():
        for line in comm.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SITE_ID="):
                site_id = line.split("=", 1)[1].strip()
            elif line.startswith("BUILDING_ID="):
                building_id = line.split("=", 1)[1].strip()
    return SitePackRef(site_id=site_id, building_id=building_id)
