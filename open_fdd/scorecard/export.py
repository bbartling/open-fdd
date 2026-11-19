"""Build a privacy-preserving review bundle on the data owner's machine, and map verdicts back.

The data owner runs this locally; only the bundle folder leaves. Nothing here connects to a database or network.

- Point names never leave: history rows are mapped point -> Open-FDD role with the owner's point map; unmapped
  points are dropped.
- Equipment ids become opaque aliases (EQ-0001, ...); site ids and every column not in the bundle format are dropped.
- Optional time shift: every timestamp moves by the same offset (whole weeks recommended, so hour of day and day of
  week, which the rules depend on, are kept).
- Only history inside +/- ``window_hours`` of a FAULT window is exported, not the full archive.
- The alias map and the shift are written to a PRIVATE folder that the owner keeps; ``unalias`` uses them to map a
  reviewer's verdicts back onto real ids and times.
- ``manifest.json`` lists a SHA-256 for every file; ``check`` / ``run --bundle`` verify them.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from open_fdd.scorecard.bundle import (
    FORMAT,
    HISTORY_FIELDS,
    ROLE_RE,
    TEMPLATE_FIELDS,
    VERSION,
)
from open_fdd.scorecard.core import RESULT_FIELDS, Config, _ts, read_csv

BUNDLE_FILES = ("rule_results.csv", "labels.csv", "verdicts.csv", "history_long.csv", "role_map.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shift(ts: str, delta: timedelta) -> str:
    """Shift a canonical UTC timestamp (from ``_ts``); output keeps the same canonical, comparable format."""
    return (datetime.fromisoformat(ts) + delta).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


SITE_SEP = "\x1f"  # joins site id + equipment id into one private key; never written to the bundle


def _norm_role(role: str) -> str | None:
    """Open-FDD role name, accepting the snake_case spelling some role maps use (``zone_air_temp``)."""
    role = role.strip()
    if ROLE_RE.match(role):
        return role
    kebab = role.lower().replace("_", "-")
    return kebab if ROLE_RE.match(kebab) else None


def _rows(path: Path, what: str):
    """CSV rows with the file name and line number in any parse error, so a bad export row is easy to find."""
    for line, r in enumerate(read_csv(path), start=2):
        if None in r or any(v is None for v in r.values()):
            raise ValueError(f"{what} ({Path(path).name}) line {line}: wrong number of columns")
        yield line, r


def build(*, results: Path, out: Path, private_dir: Path, history: Path | None = None,
          point_map: Path | None = None, labels: Path | None = None, cfg: Config | None = None,
          window_hours: float = 6.0, shift_days: int = 0, alias: bool = True,
          source_note: str = "", site_column: str = "site_id") -> dict[str, Any]:
    """Write a bundle to ``out`` and the private re-identification files to ``private_dir``.

    ``history``: long CSV ``ts, equipment_id, point, value`` (values already SI).
    ``point_map``: CSV ``point, role`` (optionally ``equipment_id``); the point names stay local.
    ``labels``: optional owner labels in the labels.csv format (aliased and shifted like everything else).
    ``site_column``: when results / history / point_map carry this column, equipment is keyed by (site, equipment),
    so the same equipment id at two sites (``AHU_1`` everywhere) gets two aliases; the site id itself never leaves.
    """
    cfg = cfg or Config()
    out, private_dir = Path(out), Path(private_dir)
    if history is not None and point_map is None:
        raise ValueError("history needs point_map (point -> role); point names never leave the machine")

    def header(path: Path | None) -> list[str]:
        if path is None:
            return []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return next(csv.reader(fh), [])

    # Key by (site, equipment) only when the results carry the site column and the history (if any) does too;
    # otherwise rows could not be matched to their history and the plain equipment id is used, as before.
    use_site = bool(site_column) and site_column in header(results) and (
        history is None or site_column in header(history))

    def key(r: dict[str, str], eq_col: str = "equipment_id") -> str:
        site = (r.get(site_column) or "").strip() if use_site else ""
        eq = str(r[eq_col]).strip()
        return f"{site}{SITE_SEP}{eq}" if site else eq

    # Validate the point map BEFORE writing anything, so a bad input never leaves a half-written bundle.
    pmap: dict[tuple[str, str], str] = {}
    renamed_roles: set[str] = set()
    if point_map is not None:
        for line, r in _rows(point_map, "point_map"):
            raw_role = (r.get("role") or "").strip()
            if not raw_role:
                continue
            role = _norm_role(raw_role)
            if role is None:
                raise ValueError(f"point_map line {line}: {raw_role!r} is not an Open-FDD role name")
            if role != raw_role:
                renamed_roles.add(raw_role)
            eq = key(r) if (r.get("equipment_id") or "").strip() else ""
            pmap[(eq, r["point"].strip())] = role
    if out.resolve() == private_dir.resolve() or private_dir.resolve().is_relative_to(out.resolve()):
        raise ValueError("private_dir must be outside the bundle folder")
    out.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    delta = timedelta(days=int(shift_days))
    aliases: dict[str, str] = {}

    def a(eq: str) -> str:
        if not alias:
            return eq.split(SITE_SEP)[-1]
        if eq not in aliases:
            aliases[eq] = f"EQ-{len(aliases) + 1:04d}"
        return aliases[eq]

    rc = cfg.results
    res_rows, faults = [], {}
    for line, r in _rows(results, "results"):
        raw = str(r[rc["status"]]).strip()
        status = cfg.status_map.get(raw, cfg.status_map.get(raw.upper(), raw.upper()))
        eq = key(r, rc["equipment_id"])
        try:
            s, e = _ts(r[rc["window_start"]]), _ts(r[rc["window_end"]])
        except ValueError as exc:
            raise ValueError(f"results line {line}: {exc}") from None
        res_rows.append({"equipment_id": a(eq), "rule_id": r[rc["rule_id"]], "window_start": _shift(s, delta),
                         "window_end": _shift(e, delta), "status": status})
        if status == "FAULT":
            faults.setdefault(eq, []).append((s, e))
    with open(out / "rule_results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(RESULT_FIELDS))
        w.writeheader()
        w.writerows(res_rows)

    lab_rows = []
    if labels:
        lc = cfg.labels
        for _, r in _rows(labels, "labels"):
            lab_rows.append({"equipment_id": a(key(r, lc["equipment_id"])),
                             "start_ts": _shift(_ts(r[lc["start_ts"]]), delta),
                             "end_ts": _shift(_ts(r[lc["end_ts"]]), delta), "label": r.get(lc["label"], ""),
                             "rule_id": r.get(lc["rule_id"], "") or "", "fault_type": r.get(lc["fault_type"], "") or "",
                             "source": r.get(lc["source"], "") or "", "reviewer": "", "notes": ""})
    with open(out / "labels.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(TEMPLATE_FIELDS))
        w.writeheader()
        w.writerows(lab_rows)

    role_map: dict[str, dict[str, Any]] = {}
    n_hist = dropped_points = 0
    if history is not None:
        pad = timedelta(hours=window_hours)
        spans: dict[str, list[tuple[str, str]]] = {}
        for eq, v in faults.items():  # padded FAULT windows, merged so each timestamp hits at most one span
            merged: list[tuple[str, str]] = []
            for s, e in sorted((_shift(s, -pad), _shift(e, pad)) for s, e in v):
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))
            spans[eq] = merged
        starts = {eq: [s for s, _ in v] for eq, v in spans.items()}
        with open(history, newline="", encoding="utf-8-sig") as src, \
                open(out / "history_long.csv", "w", newline="", encoding="utf-8") as dst:
            w = csv.writer(dst)
            w.writerow(HISTORY_FIELDS)
            for r in csv.DictReader(src):
                eq, point = key(r), str(r["point"]).strip()
                role = (pmap.get((eq, point)) or pmap.get((eq.split(SITE_SEP)[-1], point))
                        or pmap.get(("", point)))
                if role is None:
                    dropped_points += 1
                    continue
                ts = _ts(r["ts"])
                sp = spans.get(eq)
                if not sp:
                    continue
                i = bisect.bisect_right(starts[eq], ts) - 1
                if i < 0 or ts > sp[i][1]:
                    continue
                w.writerow([_shift(ts, delta), a(eq), role, r["value"]])
                role_map.setdefault(a(eq), {"kind": "", "roles": []})
                if role not in role_map[a(eq)]["roles"]:
                    role_map[a(eq)]["roles"].append(role)
                n_hist += 1
    else:
        (out / "history_long.csv").write_text(",".join(HISTORY_FIELDS) + "\n", encoding="utf-8")
    (out / "role_map.json").write_text(json.dumps(role_map, indent=2, sort_keys=True), encoding="utf-8")

    # Blank verdict sheet: one row per FAULT EPISODE (back-to-back FAULT windows of one rule on one unit merged),
    # so a reviewer judges an event once; the verdict applies to every window inside it.
    episodes: list[list[str]] = []
    for r in sorted((r for r in res_rows if r["status"] == "FAULT"),
                    key=lambda r: (r["equipment_id"], r["rule_id"], r["window_start"])):
        last = episodes[-1] if episodes else None
        if last and last[0] == r["equipment_id"] and last[1] == r["rule_id"] and r["window_start"] <= last[3]:
            last[3] = max(last[3], r["window_end"])
        else:
            episodes.append([r["equipment_id"], r["rule_id"], r["window_start"], r["window_end"]])
    with open(out / "verdicts.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(TEMPLATE_FIELDS))
        w.writeheader()
        for eq, rule, start, end in episodes:
            w.writerow({"equipment_id": eq, "start_ts": start, "end_ts": end, "label": "", "rule_id": rule,
                        "fault_type": "", "source": "reviewer", "reviewer": "", "notes": ""})

    manifest = {
        "format": FORMAT, "version": VERSION,
        # Shifted like the data: an unshifted export time next to shifted data would reveal the shift.
        "created_utc": (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source_note, "units": "SI", "timezone": "UTC",
        "privacy": {"equipment_aliased": alias, "time_shifted": bool(shift_days), "point_names": "removed",
                    "history_window_hours": window_hours},
        "files": {name: {"sha256": sha256(out / name)} for name in BUNDLE_FILES if name != "verdicts.csv"},
        "verdict_sheet": "verdicts.csv",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    private = {"alias_to_equipment": {v: k.split(SITE_SEP)[-1] for k, v in aliases.items()},
               "shift_days": int(shift_days)}
    sites = {v: k.split(SITE_SEP)[0] for k, v in aliases.items() if SITE_SEP in k}
    if sites:
        private["alias_to_site"] = sites
    (private_dir / "reidentify.json").write_text(json.dumps(private, indent=2), encoding="utf-8")
    return {"results": len(res_rows), "faults": sum(len(v) for v in faults.values()), "fault_episodes": len(episodes),
            "history_rows": n_hist,
            "dropped_unmapped_point_rows": dropped_points, "equipment": len(aliases) if alias else None,
            "renamed_roles": sorted(renamed_roles)}


def verify(bundle: Path) -> list[str]:
    """Checksum errors for a bundle ([] = every listed file matches). verdicts.csv is excluded: reviewers fill it."""
    root = Path(bundle)
    m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errs = []
    for name, meta in (m.get("files") or {}).items():
        p = root / name
        if not p.is_file():
            errs.append(f"{name}: missing")
        elif sha256(p) != meta.get("sha256"):
            errs.append(f"{name}: SHA-256 mismatch (file changed after export)")
    return errs


def unalias(verdicts: Path, private_dir: Path, out: Path) -> int:
    """Map a filled verdict sheet back to real equipment ids and times, on the owner's machine."""
    private = json.loads((Path(private_dir) / "reidentify.json").read_text(encoding="utf-8"))
    back = private["alias_to_equipment"]
    sites = private.get("alias_to_site") or {}
    delta = -timedelta(days=int(private.get("shift_days", 0)))
    n = 0
    fields = (["site_id"] if sites else []) + list(TEMPLATE_FIELDS)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in read_csv(verdicts):
            if not (r.get("label") or "").strip():
                continue
            row = {k: r.get(k, "") for k in TEMPLATE_FIELDS}
            if sites:
                row["site_id"] = sites.get(r["equipment_id"], "")
            row["equipment_id"] = back.get(r["equipment_id"], r["equipment_id"])
            row["start_ts"] = _shift(_ts(r["start_ts"]), delta)
            row["end_ts"] = _shift(_ts(r["end_ts"]), delta)
            w.writerow(row)
            n += 1
    return n
