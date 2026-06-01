"""Generate BRICK TTL from model.json (no rdflib required)."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
import tempfile
from pathlib import Path

from .model_store import ModelStore
from .paths import model_ttl_path

_log = logging.getLogger(__name__)


def _escape(value: str) -> str:
    out: list[str] = []
    for ch in value:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _safe_brick_type(value: str, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return fallback
    if not (token[0].isalpha() or token[0] == "_"):
        token = f"_{token}"
    return token


def _sanitize_local_name(value: object) -> str | None:
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
                continue
            sid = _sanitize_local_name(site.get("id"))
            if sid is None:
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
                continue
            eid = _sanitize_local_name(eq.get("id"))
            sid = _sanitize_local_name(eq.get("site_id"))
            if eid is None or sid is None:
                continue
            et = _safe_brick_type(str(eq.get("equipment_type") or "Equipment"), "Equipment")
            lines.append(f":eq_{eid} a brick:{et} ;")
            lines.append(f'  rdfs:label "{_escape(str(eq.get("name", "Equipment")))}" ;')
            inst = eq.get("bacnet_device_instance")
            if inst is None:
                inst = eq.get("bacnet_device_id")
            if inst is not None and str(inst).strip() != "":
                lines.append(f'  ofdd:bacnetDeviceInstance "{_escape(str(inst))}" ;')
            feeds = eq.get("feeds") if isinstance(eq.get("feeds"), list) else []
            for target in feeds:
                tid = _sanitize_local_name(target)
                if tid is not None:
                    lines.append(f"  brick:feeds :eq_{tid} ;")
            lines.append(f'  brick:isPartOf :site_{sid} .')
            lines.append("")
        for pt in model.get("points", []):
            if not isinstance(pt, dict):
                continue
            pid = _sanitize_local_name(pt.get("id"))
            if pid is None:
                continue
            bt = _safe_brick_type(str(pt.get("brick_type") or "Point"), "Point")
            pt_label = str(pt.get("name") or pt.get("description") or pt.get("external_id") or pid)
            lines.append(f":pt_{pid} a brick:{bt} ;")
            lines.append(f'  rdfs:label "{_escape(pt_label)}" ;')
            if pt.get("equipment_id"):
                eid = _sanitize_local_name(pt.get("equipment_id"))
                if eid is not None:
                    lines.append(f"  brick:isPointOf :eq_{eid} ;")
            maps_rule_input = str(pt.get("fdd_input") or "").strip()
            if not maps_rule_input and bt and bt != "Point":
                maps_rule_input = str(bt).strip()
            if maps_rule_input:
                lines.append(f'  ofdd:mapsToRuleInput "{_escape(maps_rule_input)}" ;')
            from .timeseries_api import plot_column_name

            ts_col = plot_column_name(pt)
            if ts_col:
                lines.append(f'  ofdd:timeseriesColumn "{_escape(ts_col)}" ;')
            ext = pt.get("metadata", {}).get("external_ref") if isinstance(pt.get("metadata"), dict) else None
            if ext:
                lines.append(f'  ofdd:externalReference "{_escape(str(ext))}" ;')
            meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
            if pt.get("bacnet_device_id") is not None:
                lines.append(f'  ofdd:bacnetDeviceId "{_escape(str(pt.get("bacnet_device_id")))}" ;')
            if pt.get("object_identifier"):
                lines.append(f'  ofdd:bacnetObjectIdentifier "{_escape(str(pt.get("object_identifier")))}" ;')
            if meta.get("series_id"):
                lines.append(f'  ofdd:seriesId "{_escape(str(meta.get("series_id")))}" ;')
            if meta.get("poll_interval_s"):
                lines.append(f'  ofdd:pollIntervalS "{_escape(str(meta.get("poll_interval_s")))}" ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")
        return "\n".join(lines)

    def sync(self) -> Path:
        from .model_feeds import ensure_model_feeds
        from .model_service import ModelService

        with ModelService().transaction() as model:
            ensure_model_feeds(model)
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
        return self.ttl_path
