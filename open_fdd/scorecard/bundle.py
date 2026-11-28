"""Offline export bundle: what a site sends for review when nobody has access to its database.

A bundle is a plain folder (zip it to send) of UTF-8 CSV + JSON, SI units, UTC timestamps, Open-FDD role names
only (never BAS point names):

    manifest.json        {"format": "open-fdd-scorecard-bundle", "version": 1, "created_utc": "...", "files":
                          {"rule_results.csv": {"sha256": "..."}, ...}, "privacy": {...},
                          "source": "free text, no site names", "rules": "pack/version the results came from"}
    rule_results.csv     equipment_id, rule_id, window_start, window_end, status   (required; extra columns kept out)
    verdicts.csv         same columns as labels.csv: the blank verdict sheet the reviewer fills in (not checksummed)
    labels.csv           equipment_id, start_ts, end_ts, label, rule_id, fault_type, source, reviewer, notes
                         (optional; label = fault / normal, or confirmed / false_positive; blank label = not reviewed)
    history_long.csv     ts, equipment_id, role, value  (optional; SI history around each FAULT window)
    role_map.json        {"<equipment_id>": {"kind": "ahu", "roles": ["discharge_air_temperature", ...]}}  (optional)
    config.json          column / value mapping for rule_results.csv and labels.csv (optional, see core.Config)

``equipment_id`` may be an opaque alias (e.g. AHU-0007); the bundle never needs real names.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from open_fdd.scorecard.core import RESULT_FIELDS, Config, _ts, load_config, read_csv

FORMAT = "open-fdd-scorecard-bundle"
VERSION = 1
ROLE_RE = re.compile(r"^[a-z][a-z0-9]*([_-][a-z0-9]+)*$")
TEMPLATE_FIELDS = ("equipment_id", "start_ts", "end_ts", "label", "rule_id", "fault_type", "source", "reviewer",
                   "notes")
HISTORY_FIELDS = ("ts", "equipment_id", "role", "value")


def load(bundle: str | Path) -> tuple[list[dict], list[dict], Config]:
    root = Path(bundle)
    cfg = load_config(root / "config.json" if (root / "config.json").is_file() else None)
    results = read_csv(root / "rule_results.csv")
    labels = []
    for name in ("labels.csv", "verdicts.csv"):
        if (root / name).is_file():
            labels += read_csv(root / name)
    return results, labels, cfg


def check(bundle: str | Path) -> dict[str, Any]:
    """Validate a bundle offline. Returns {"ok": bool, "errors": [...], "warnings": [...], "stats": {...}}."""
    root = Path(bundle)
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, Any] = {}
    man = root / "manifest.json"
    if not man.is_file():
        errors.append("manifest.json missing")
    else:
        m = json.loads(man.read_text(encoding="utf-8"))
        if m.get("format") != FORMAT:
            errors.append(f"manifest.format must be {FORMAT!r}")
        if m.get("version") != VERSION:
            errors.append(f"manifest.version must be {VERSION}")
        if m.get("files"):
            from open_fdd.scorecard.export import verify
            errors += verify(root)
    if not (root / "rule_results.csv").is_file():
        errors.append("rule_results.csv missing")
        return {"ok": False, "errors": errors, "warnings": warnings, "stats": stats}
    results, labels, cfg = load(root)
    if results:
        missing = [cfg.results[f] for f in RESULT_FIELDS if cfg.results[f] not in results[0]]
        if missing:
            errors.append(f"rule_results.csv: missing columns {missing}")
    faults = []
    if not errors:
        for i, r in enumerate(results, start=2):
            try:
                s, e = _ts(r[cfg.results["window_start"]]), _ts(r[cfg.results["window_end"]])
            except (ValueError, KeyError) as exc:
                errors.append(f"rule_results.csv line {i}: bad timestamp ({exc})")
                break
            if e <= s:
                errors.append(f"rule_results.csv line {i}: window_end not after window_start")
                break
            if cfg.status_map.get(str(r[cfg.results["status"]]).upper(), cfg.status_map.get(
                    str(r[cfg.results["status"]]))) == "FAULT":
                faults.append((r[cfg.results["equipment_id"]], s, e))
    stats.update(results=len(results), faults=len(faults),
                 labels=sum(1 for lab in labels if (lab.get(cfg.labels["label"]) or "").strip()),
                 unreviewed_template_rows=sum(1 for lab in labels if not (lab.get(cfg.labels["label"]) or "").strip()))
    hist = root / "history_long.csv"
    if hist.is_file():
        covered: dict[str, list[str]] = {}
        roles_seen: set[str] = set()
        with open(hist, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            if tuple(rd.fieldnames or ()) [:4] != HISTORY_FIELDS:
                errors.append(f"history_long.csv: header must start with {list(HISTORY_FIELDS)}")
            else:
                for row in rd:
                    roles_seen.add(row["role"])
                    covered.setdefault(row["equipment_id"], []).append(_ts(row["ts"]))
        bad_roles = sorted(r for r in roles_seen if not ROLE_RE.match(r))
        if bad_roles:
            errors.append(f"history_long.csv: roles must be Open-FDD role names, not point names: {bad_roles[:10]}")
        for v in covered.values():
            v.sort()
        import bisect
        no_hist = 0
        for eq, s, e in faults:
            ts = covered.get(eq, [])
            if bisect.bisect_left(ts, e) - bisect.bisect_left(ts, s) == 0:
                no_hist += 1
        stats.update(history_rows=sum(len(v) for v in covered.values()), roles=sorted(roles_seen),
                     faults_without_history=no_hist)
        if no_hist:
            warnings.append(f"{no_hist} FAULT windows have no history rows inside the window")
    else:
        warnings.append("history_long.csv missing: reviewers cannot see the trend behind each FAULT")
    rm = root / "role_map.json"
    if rm.is_file():
        for eq, spec in json.loads(rm.read_text(encoding="utf-8")).items():
            bad = [r for r in (spec or {}).get("roles", []) if not ROLE_RE.match(str(r))]
            if bad:
                errors.append(f"role_map.json {eq}: not role names: {bad[:5]}")
    else:
        warnings.append("role_map.json missing")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def verdict_template(bundle: str | Path, out: str | Path) -> int:
    """Write labels.csv-shaped rows (label blank) for every FAULT window with no verdict yet; return the count."""
    from open_fdd.scorecard.core import score

    results, labels, cfg = load(bundle)
    card = score(results, labels, cfg)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(TEMPLATE_FIELDS))
        w.writeheader()
        for q in card["review_queue"]:
            w.writerow({"equipment_id": q["equipment_id"], "start_ts": q["window_start"], "end_ts": q["window_end"],
                        "label": "", "rule_id": q["rule_id"], "fault_type": "", "source": "technician",
                        "reviewer": "", "notes": ""})
    return len(card["review_queue"])
