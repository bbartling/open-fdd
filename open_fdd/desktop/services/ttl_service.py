from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from open_fdd.desktop.storage.model_store import ModelStore
from open_fdd.desktop.storage.paths import model_ttl_mirror_path, model_ttl_path

_log = logging.getLogger(__name__)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _safe_brick_type(value: str, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        _log.warning("Invalid BRICK type '%s'; using fallback '%s'", value, fallback)
        return fallback
    if not (token[0].isalpha() or token[0] == "_"):
        token = f"_{token}"
    if token != value:
        _log.warning("Adjusted BRICK type '%s' -> '%s'", value, token)
    return token


def _sanitize_local_name(value: Any) -> str | None:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return None
    if token[0].isdigit():
        token = f"_{token}"
    return token


@dataclass
class TtlService:
    model_store: ModelStore = field(default_factory=ModelStore)
    ttl_path: Path = field(default_factory=model_ttl_path)
    ttl_mirror_path: Path | None = field(default_factory=model_ttl_mirror_path)

    def build_ttl(self) -> str:
        model = self.model_store.load()
        lines = [
            "@prefix brick: <https://brickschema.org/schema/Brick#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix ofdd: <http://openfdd.local/ontology#> .",
            "@prefix : <http://openfdd.local/site#> .",
            "",
        ]
        for site in model.get("sites", []):
            if not isinstance(site, dict):
                _log.warning("Skipping invalid site row (expected dict): %r", site)
                continue
            raw_site_id = site.get("id")
            sid = _sanitize_local_name(raw_site_id)
            if sid is None:
                _log.warning("Skipping site with invalid id: %r", raw_site_id)
                continue
            lines.append(f":site_{sid} a brick:Site ;")
            lines.append(f'  rdfs:label "{_escape(str(site.get("name", "Site")))}" ;')
            site_metadata = site.get("metadata") if isinstance(site.get("metadata"), dict) else {}
            rule_pack = site_metadata.get("rule_pack")
            if rule_pack:
                lines.append(f'  ofdd:faultRulePack "{_escape(str(rule_pack))}" ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")
        for eq in model.get("equipment", []):
            if not isinstance(eq, dict):
                _log.warning("Skipping invalid equipment row (expected dict): %r", eq)
                continue
            raw_eq_id = eq.get("id")
            raw_site_id = eq.get("site_id")
            eid = _sanitize_local_name(raw_eq_id)
            sid = _sanitize_local_name(raw_site_id)
            if eid is None or sid is None:
                _log.warning("Skipping equipment with invalid id/site_id: id=%r site_id=%r", raw_eq_id, raw_site_id)
                continue
            et = _safe_brick_type(str(eq.get("equipment_type") or "Equipment"), "Equipment")
            lines.append(f":eq_{eid} a brick:{et} ;")
            lines.append(f'  rdfs:label "{_escape(str(eq.get("name", "Equipment")))}" ;')
            lines.append(f'  brick:isPartOf :site_{sid} .')
            lines.append("")
        for pt in model.get("points", []):
            if not isinstance(pt, dict):
                _log.warning("Skipping invalid point row (expected dict): %r", pt)
                continue
            raw_point_id = pt.get("id")
            pid = _sanitize_local_name(raw_point_id)
            if pid is None:
                _log.warning("Skipping point with invalid id: %r", raw_point_id)
                continue
            bt = _safe_brick_type(str(pt.get("brick_type") or "Point"), "Point")
            lines.append(f":pt_{pid} a brick:{bt} ;")
            lines.append(f'  rdfs:label "{_escape(str(pt.get("external_id", "")))}" ;')
            if pt.get("equipment_id"):
                eid = _sanitize_local_name(pt.get("equipment_id"))
                if eid is None:
                    _log.warning("Skipping point equipment_id link with invalid value: %r", pt.get("equipment_id"))
                else:
                    lines.append(f"  brick:isPointOf :eq_{eid} ;")
            if pt.get("fdd_input"):
                lines.append(f'  ofdd:mapsToRuleInput "{_escape(str(pt["fdd_input"]))}" ;')
            ext = pt.get("metadata", {}).get("external_ref") if isinstance(pt.get("metadata"), dict) else None
            if ext:
                lines.append(f'  ofdd:externalReference "{_escape(str(ext))}" ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")
        return "\n".join(lines)

    def sync(self) -> Path:
        ttl = self.build_ttl()
        self.ttl_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self.ttl_path.name}.", suffix=".tmp", dir=str(self.ttl_path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
                handle.write(ttl)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.ttl_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        if self.ttl_mirror_path is not None:
            self.ttl_mirror_path.parent.mkdir(parents=True, exist_ok=True)
            self.ttl_mirror_path.write_text(ttl, encoding="utf-8")
        return self.ttl_path

