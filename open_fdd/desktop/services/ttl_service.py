from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any

from open_fdd.desktop.storage.model_store import ModelStore
from open_fdd.desktop.storage.paths import model_ttl_path

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


@dataclass
class TtlService:
    model_store: ModelStore = field(default_factory=ModelStore)
    ttl_path: Path = field(default_factory=model_ttl_path)

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
            sid = str(site["id"]).replace("-", "_")
            lines.append(f":site_{sid} a brick:Site ;")
            lines.append(f'  rdfs:label "{_escape(str(site.get("name", "Site")))}" ;')
            site_metadata = site.get("metadata") if isinstance(site.get("metadata"), dict) else {}
            rule_pack = site_metadata.get("rule_pack")
            if rule_pack:
                lines.append(f'  ofdd:faultRulePack "{_escape(str(rule_pack))}" ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")
        for eq in model.get("equipment", []):
            eid = str(eq["id"]).replace("-", "_")
            sid = str(eq["site_id"]).replace("-", "_")
            et = _safe_brick_type(str(eq.get("equipment_type") or "Equipment"), "Equipment")
            lines.append(f":eq_{eid} a brick:{_escape(et)} ;")
            lines.append(f'  rdfs:label "{_escape(str(eq.get("name", "Equipment")))}" ;')
            lines.append(f'  brick:isPartOf :site_{sid} .')
            lines.append("")
        for pt in model.get("points", []):
            pid = str(pt["id"]).replace("-", "_")
            bt = _safe_brick_type(str(pt.get("brick_type") or "Point"), "Point")
            lines.append(f":pt_{pid} a brick:{_escape(bt)} ;")
            lines.append(f'  rdfs:label "{_escape(str(pt.get("external_id", "")))}" ;')
            if pt.get("equipment_id"):
                lines.append(f'  brick:isPointOf :eq_{str(pt["equipment_id"]).replace("-", "_")} ;')
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
        self.ttl_path.write_text(ttl, encoding="utf-8")
        return self.ttl_path

