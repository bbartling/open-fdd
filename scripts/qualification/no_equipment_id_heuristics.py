#!/usr/bin/env python3
"""Fail closed when product code selects equipment by id text.

Source gate for #1037–#1042 and #1045–#1047. It scans product trees and the
agent-spec pages that must not authorize id heuristics. It does not talk to a
hub, and a green run is not tip+field stress and not fully_qualified.

Zone-temp charts still join by the mapped ``zone-air-temp`` role across
stamped zone-family kinds. That is a role join, not an ``equipment_id`` filter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path


PRODUCT_ROOTS = (
    "services/central/src",
    "services/fieldbus/src",
    "edge/src",
    "crates",
    "frontend/web/src",
    "sql_rules",
    "open_fdd",
    "tools/wattlab_export",
    "mcp",
)

SOURCE_SUFFIXES = {".rs", ".py", ".ts", ".tsx", ".sql"}

POLICY_FILES = (
    "openfdd_agent_spec/DATA_CONTRACT.md",
    "openfdd_agent_spec/AGENTS.md",
    "openfdd_agent_spec/skills/data-modeling/SKILL.md",
    "docs/agent/PACKAGE_AUTHORING.md",
    "docs/web-app/rcx-plots-by-hvac.md",
)

# Phrases that describe id-text classification as a supported fallback.
BANNED_POLICY = (
    "heuristics are fallback",
    "preferred over id heuristics",
    "package stamp / id heuristics",
    "vendor-neutral id heuristics",
    "id heuristics are the fallback",
)

_CODE_PATTERNS = (
    re.compile(r"(?i)\bequipment_id\b[^\n;]{0,80}\b(?:not\s+)?(?:i?like)\b"),
    re.compile(
        r"(?i)\bupper\s*\(\s*(?:cast\s*\(\s*)?equipment_id\b[^\n]{0,40}\b(?:i?like)\b"
    ),
    re.compile(r"(?i)\bequipment_id\s*\.\s*upper\s*\(\s*\)\s*\.\s*startswith\s*\("),
    re.compile(r"(?i)\bequipment_id\s*\.\s*startswith\s*\("),
    re.compile(r"(?i)\bequipment_id\s*\.\s*startsWith\s*\("),
    re.compile(
        r"(?i)[\"'](?:VAV|AHU|ZONE|CHILLER|WEATHER|CHW|LOOPBACK)[\"']\s+in\s+"
        r"(?:\([^)\n]{0,40}\)?\s*)?(?:\w+\.)?equipment_id\b"
    ),
    re.compile(r"(?i)\bequipment_id\b[^\n]{0,40}\.(?:includes|contains)\s*\(\s*[\"']"),
    re.compile(r"\bchiller_like_equipment_sql\b"),
    re.compile(r"\binfer_kind_from_id\b"),
    re.compile(r"\bis_heat_pump_id\b"),
    re.compile(r"\bis_zone_terminal_id\b"),
    re.compile(r"\bisWeatherEquipmentId\b"),
    re.compile(r"\bfn\s+infer_eq_type\b"),
)

_NEGATION = re.compile(
    r"(?i)\b(?:must\s+not|do\s+not|does\s+not|don't|never)\b"
    r"|!\s*.*\.contains\s*\("
    r"|assert\s*!\s*\("
)

_KIND = {
    "ahu": "ahu",
    "airhandler": "ahu",
    "airhandlingunit": "ahu",
    "rtu": "ahu",
    "mau": "ahu",
    "doas": "ahu",
    "cvahu": "ahu",
    "vavahu": "ahu",
    "unitventilator": "ahu",
    "uv": "ahu",
    "erv": "ahu",
    "energyrecoveryventilator": "ahu",
    "vav": "vav",
    "zoneterminal": "vav",
    "zoneother": "zone_other",
    "zone": "zone_other",
    "fcu": "zone_other",
    "fancoil": "zone_other",
    "fancoilunit": "zone_other",
    "standaloneddc": "zone_other",
    "ddczone": "zone_other",
    "zoneddc": "zone_other",
    "vrf": "vrf",
    "chiller": "chiller",
    "chwplant": "chiller",
    "chilledwaterplant": "chiller",
    "coolingtower": "cooling_tower",
    "tower": "cooling_tower",
    "boiler": "boiler",
    "hwplant": "boiler",
    "hotwaterplant": "boiler",
    "heatpump": "heatpump",
    "hp": "heatpump",
    "baseboard": "baseboard",
    "baseboardheat": "baseboard",
    "weather": "weather",
    "meter": "meter",
    "electricmeter": "meter",
    "utilitymeter": "meter",
    "powermeter": "meter",
}

ZONE_KINDS = frozenset({"vav", "zone_other", "baseboard", "heatpump"})


def canonical_kind(raw: object) -> str | None:
    """Recognized package stamp. Display ``GENERAL`` / ``PLANT`` stay unknown."""
    if raw is None:
        return None
    key = "".join(ch for ch in str(raw).lower() if ch.isalnum())
    if not key or key in {"general", "unknown", "plant"}:
        return None
    return _KIND.get(key)


def kind_of_record(record: dict) -> str | None:
    for field in ("equipment_type_raw", "equipType", "equipment_type"):
        kind = canonical_kind(record.get(field))
        if kind:
            return kind
    return None


def equipment_records(body: object) -> list[dict]:
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        rows = body.get("equipment") or body.get("items") or []
    else:
        return []
    out: list[dict] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        elif isinstance(row, str) and row:
            out.append({"equipment_id": row})
    return out


def pick_equipment_id(records: list[dict], kind: str) -> str:
    """First exact id whose stamp is ``kind``. Id text is not a preference."""
    hits = []
    for record in records:
        equipment_id = str(record.get("equipment_id") or record.get("id") or "").strip()
        if equipment_id and kind_of_record(record) == kind:
            hits.append(equipment_id)
    hits.sort()
    return hits[0] if hits else ""


def _envelope(body: object) -> dict:
    if not isinstance(body, dict):
        return {}
    nested = body.get("analytics")
    if isinstance(nested, dict):
        return nested
    return body


def equipment_ids_in_envelope(body: object) -> list[str]:
    env = _envelope(body)
    found: list[str] = []
    seen: set[str] = set()
    for key in ("points", "rows", "equipment"):
        rows = env.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            equipment_id = str(row.get("equipment_id") or "").strip()
            if equipment_id and equipment_id not in seen:
                seen.add(equipment_id)
                found.append(equipment_id)
    return found


def check_preset_membership(
    cohort: str,
    envelope: object,
    inventory: list[dict],
) -> list[str]:
    """Stamp contradictions and id-LIKE text in a preset payload.

    ``ahu`` requires kind ``ahu``. ``zone`` allows zone-family stamps and
    unclassified ids (mapped zone role, no stamp). A contradictory stamp fails.
    Empty points are not a failure: inclusion still needs live historian rows.
    """
    if cohort not in {"ahu", "zone"}:
        return [f"unknown cohort {cohort}"]
    violations: list[str] = []
    blob = json.dumps(envelope) if not isinstance(envelope, str) else envelope
    if re.search(r"(?i)\bequipment_id\b[^\n]{0,80}\b(?:not\s+)?(?:i?like)\b", blob):
        violations.append("preset payload filters equipment_id with LIKE/ILIKE")
    by_id = {}
    for record in inventory:
        equipment_id = str(record.get("equipment_id") or record.get("id") or "").strip()
        if equipment_id:
            by_id[equipment_id] = kind_of_record(record)
    for equipment_id in equipment_ids_in_envelope(envelope):
        kind = by_id.get(equipment_id)
        if cohort == "ahu" and kind != "ahu":
            violations.append(
                f"{equipment_id} is {kind or 'unclassified'}, not ahu, on an AHU preset"
            )
        elif cohort == "zone" and kind is not None and kind not in ZONE_KINDS:
            violations.append(
                f"{equipment_id} stamp {kind} is not a zone-family kind"
            )
    return violations


def _skip_source(path: Path) -> bool:
    if path.suffix not in SOURCE_SUFFIXES:
        return True
    name = path.name
    if name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
        return True
    parts = set(path.parts)
    return bool(parts & {"target", "node_modules", "__pycache__", "dist"})


def _code_line_violation(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("//", "#", "--", "*", "/*", "///", "//!")):
        return False
    if not any(pattern.search(line) for pattern in _CODE_PATTERNS):
        return False
    return _NEGATION.search(line) is None


def scan_source(root: Path) -> list[str]:
    findings: list[str] = []
    for rel in PRODUCT_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or _skip_source(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if _code_line_violation(line):
                    findings.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
    return findings


def scan_policy(root: Path) -> list[str]:
    findings: list[str] = []
    for rel in POLICY_FILES:
        path = root / rel
        if not path.is_file():
            findings.append(f"{rel}: missing policy file")
            continue
        text = path.read_text(encoding="utf-8")
        if "unclassified" not in text or "Do not infer" not in text:
            findings.append(
                f"{rel}: must say a missing stamp is unclassified and "
                "'Do not infer' kind from equipment_id"
            )
        lower = text.lower()
        for phrase in BANNED_POLICY:
            if phrase in lower:
                findings.append(f"{rel}: authorizes id heuristics ({phrase})")
    return findings


def scan(root: Path) -> list[str]:
    return scan_source(root) + scan_policy(root)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _policy_stub() -> str:
    return (
        "A missing or unrecognized stamp is unclassified. "
        "Do not infer kind from equipment_id.\n"
    )


def selftest() -> int:
    """The scanner must flag a LIKE filter and ignore a negated assertion."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in POLICY_FILES:
            _write(root / rel, _policy_stub())
        _write(
            root / "services/central/src/bad.rs",
            'let sql = "WHERE equipment_id LIKE \'AHU%\'";\n',
        )
        _write(
            root / "services/central/src/note.rs",
            "// equipment_id LIKE is not a selector\n"
            "assert!(!upper.contains(\"EQUIPMENT_ID LIKE\"));\n",
        )
        _write(
            root / "sql_rules/oat_meteo_fault.sql",
            "-- This file does not filter equipment_id by prefix or LIKE.\n"
            "SELECT equipment_id FROM history\n",
        )
        hits = scan(root)
        if len(hits) != 1 or "bad.rs" not in hits[0]:
            print("SELFTEST FAIL: expected only bad.rs", file=sys.stderr)
            for hit in hits:
                print(hit, file=sys.stderr)
            return 1
        _write(
            root / "docs/agent/PACKAGE_AUTHORING.md",
            _policy_stub() + "generic equipment-id heuristics are fallback only\n",
        )
        policy_hits = scan_policy(root)
        if not any("heuristics are fallback" in hit for hit in policy_hits):
            print("SELFTEST FAIL: banned policy phrase was ignored", file=sys.stderr)
            return 1
    inventory = [
        {"equipment_id": "AHU_GHOST", "equipment_type": "VAV"},
        {"equipment_id": "AC_1", "equipment_type_raw": "ahu"},
        {"equipment_id": "jci_vav_1", "equipType": "vav"},
        {"equipment_id": "bldg2-zone-loopback"},
    ]
    picked = pick_equipment_id(inventory, "ahu")
    if picked != "AC_1":
        print(f"SELFTEST FAIL: picked {picked!r}, want AC_1", file=sys.stderr)
        return 1
    ahu_bad = check_preset_membership(
        "ahu",
        {"points": [{"equipment_id": "AHU_GHOST"}, {"equipment_id": "AC_1"}]},
        inventory,
    )
    if not any("AHU_GHOST" in item for item in ahu_bad):
        print("SELFTEST FAIL: AHU preset accepted a VAV stamp", file=sys.stderr)
        return 1
    zone_ok = check_preset_membership(
        "zone",
        {
            "points": [
                {"equipment_id": "jci_vav_1"},
                {"equipment_id": "bldg2-zone-loopback"},
            ]
        },
        inventory,
    )
    if zone_ok:
        print(f"SELFTEST FAIL: zone role join flagged {zone_ok}", file=sys.stderr)
        return 1
    zone_bad = check_preset_membership(
        "zone",
        {"points": [{"equipment_id": "AC_1"}]},
        inventory,
    )
    if not zone_bad:
        print("SELFTEST FAIL: zone preset accepted an AHU stamp", file=sys.stderr)
        return 1
    like_bad = check_preset_membership(
        "ahu",
        {"warnings": ["WHERE equipment_id LIKE 'AHU%'"]},
        inventory,
    )
    if not any("LIKE" in item for item in like_bad):
        print("SELFTEST FAIL: LIKE payload was accepted", file=sys.stderr)
        return 1
    print("SELFTEST PASS")
    return 0


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--pick-kind", choices=("ahu", "vav", "weather"))
    parser.add_argument("--check-preset", choices=("ahu", "zone"))
    parser.add_argument("--equipment-json", type=Path)
    parser.add_argument("--envelope", type=Path)
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.pick_kind or args.check_preset:
        if args.equipment_json is None:
            print("equipment json is required", file=sys.stderr)
            return 2
        records = equipment_records(_load_json(args.equipment_json))
        if args.pick_kind:
            print(pick_equipment_id(records, args.pick_kind))
            return 0
        if args.envelope is None:
            print("envelope json is required", file=sys.stderr)
            return 2
        violations = check_preset_membership(
            args.check_preset, _load_json(args.envelope), records
        )
        ids = equipment_ids_in_envelope(_load_json(args.envelope))
        if not ids:
            print(
                f"WARN: {args.check_preset} preset returned no equipment ids; "
                "inclusion of stamped opaque ids is not proven"
            )
        for item in violations:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1 if violations else 0
    root = args.root or Path(__file__).resolve().parents[2]
    findings = scan(root)
    if findings:
        print(f"FAIL: {len(findings)} equipment-id heuristic hit(s)", file=sys.stderr)
        for item in findings:
            print(item, file=sys.stderr)
        return 1
    print("PASS: no equipment-id LIKE/heuristic selectors in product source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
