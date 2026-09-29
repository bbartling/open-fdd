#!/usr/bin/env python3
"""Host disk preflight for the 100 GiB oldest-first data budget.

Mirrors ``preflight_update`` in ``crates/fdd_store/src/disk_budget.rs``.
Run this before an on-box backup or patch. A ~200 GiB edge must not be
assumed to hold 100 GiB of live parquet plus a second full copy.

Exit codes:
  0  proceed with backup
  10 skip backup (headroom, or a test deploy that was not asked to back up)
  11 prune oldest parquet, then back up
  20 fail closed
  2  usage or runtime error

``--self-test`` checks the same numeric cases as the Rust unit test.
Field proof on a live edge disk is out of band.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

GIB = 1024 * 1024 * 1024
DEFAULT_BUDGET_GIB = 100
DEFAULT_RESERVED_PERCENT = 10
EXIT_PROCEED = 0
EXIT_SKIP = 10
EXIT_PRUNE = 11
EXIT_FAIL = 20
METADATA_SNAPSHOT_BYTES = 64 * 1024 * 1024

RESULTS_DIR = "analytics_results"


def env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip() in {"1", "true", "TRUE", "yes", "YES", "on", "ON"}


def budget_enabled() -> bool:
    railway = bool(os.environ.get("RAILWAY_ENVIRONMENT", "").strip())
    flag = os.environ.get("OPENFDD_DATA_BUDGET_ENABLED")
    if flag is None:
        return not railway
    return env_truthy(flag)


def budget_bytes() -> int:
    raw = os.environ.get("OPENFDD_LOCAL_DATA_BUDGET_GIB", "").strip()
    try:
        gib = int(raw) if raw else DEFAULT_BUDGET_GIB
    except ValueError:
        gib = DEFAULT_BUDGET_GIB
    if gib <= 0:
        gib = DEFAULT_BUDGET_GIB
    return gib * GIB


def reserved_percent() -> int:
    raw = os.environ.get("OPENFDD_DISK_RESERVED_FREE_PERCENT", "").strip()
    try:
        pct = int(raw) if raw else DEFAULT_RESERVED_PERCENT
    except ValueError:
        pct = DEFAULT_RESERVED_PERCENT
    return max(1, min(50, pct))


def preflight_update(inp: dict) -> dict:
    pct = max(0, min(50, int(inp["reserved_free_percent"])))
    reserved = int(inp["disk_total_bytes"]) * pct // 100
    free_after = int(inp["disk_free_bytes"]) + int(inp["bytes_over_budget"])
    if inp["test_deploy"] and not inp["operator_requested_backup"]:
        if int(inp["disk_free_bytes"]) < reserved and int(inp["bytes_over_budget"]) == 0:
            return {
                "decision": "fail_closed",
                "reason": "free space is below the reserved percent; refusing the update",
            }
        return {
            "decision": "skip_backup",
            "reason": "test deploy skips on-box backup unless OPENFDD_BACKUP_ON_UPDATE=1",
        }
    free_for_backup = free_after if int(inp["bytes_over_budget"]) > 0 else int(inp["disk_free_bytes"])
    fits = free_for_backup >= int(inp["backup_bytes"]) + reserved
    if fits:
        if int(inp["bytes_over_budget"]) > 0:
            return {
                "decision": "prune_then_backup",
                "reclaim_bytes": int(inp["bytes_over_budget"]),
            }
        return {"decision": "proceed"}
    if free_for_backup < reserved:
        return {
            "decision": "fail_closed",
            "reason": "free space stays below the reserved percent even without an on-box backup",
        }
    if inp["backup_required"]:
        return {
            "decision": "fail_closed",
            "reason": "on-box backup plus reserved free space exceeds disk headroom",
        }
    return {
        "decision": "skip_backup",
        "reason": "insufficient headroom for an on-box backup; do not assume 2x live data fits on a ~200 GiB edge",
    }


def _part_stamp_key(text: str) -> int | None:
    search = 0
    marker = "part-"
    while True:
        rel = text.find(marker, search)
        if rel < 0:
            return None
        start = rel + len(marker)
        rest = text[start:]
        if (
            len(rest) >= 16
            and rest[8] == "T"
            and rest[15] in "Z-."
            and rest[:8].isdigit()
            and rest[9:15].isdigit()
        ):
            digits = rest[0:4] + rest[4:6] + rest[6:8] + rest[9:11] + rest[11:13] + rest[13:15]
            return int(digits)
        search = start
        if search >= len(text):
            return None


def _year_month_key(text: str) -> int | None:
    def capture(marker: str) -> int | None:
        idx = text.find(marker)
        if idx < 0:
            return None
        rest = text[idx + len(marker) :]
        digits = []
        for ch in rest:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            return None
        return int("".join(digits))

    year = capture("year=")
    month = capture("month=")
    if year is None or month is None:
        return None
    if not (1 <= month <= 12 and 1970 <= year <= 9999):
        return None
    return year * 10_000_000_000 + month * 100_000_000 + 1_000_000


def order_key(path: Path, mtime: int) -> int:
    text = str(path)
    stamped = _part_stamp_key(text)
    if stamped is not None:
        return stamped
    hive = _year_month_key(text)
    if hive is not None:
        return hive
    return mtime


def legacy_building_hive_segment(seg: str) -> bool:
    key, sep, value = seg.partition("=")
    return bool(sep) and key == "building" and value != "" and "=" not in value


def _budget_tree(parts: list[str]) -> bool:
    if not parts:
        return False
    if parts[0] in {"history", RESULTS_DIR} or legacy_building_hive_segment(parts[0]):
        return True
    if parts[0] == "tenants":
        return any(p in {"history", RESULTS_DIR} for p in parts) or len(parts) <= 2
    return False


def in_budget(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    parts = list(rel.parts)
    if any(p in {"backups", "archives"} for p in parts):
        return False
    return _budget_tree(parts)


def collect_objects(root: Path) -> list[dict]:
    out: list[dict] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        kept_dirs = []
        for name in dirnames:
            child = current / name
            if child == root or in_budget(child, root) or _ancestor_budget(child, root):
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            path = current / name
            if path.suffix.lower() != ".parquet":
                continue
            if not in_budget(path, root):
                continue
            st = path.stat()
            out.append(
                {
                    "path": path,
                    "bytes": st.st_size,
                    "order_key": order_key(path, int(st.st_mtime)),
                }
            )
    return out


def _ancestor_budget(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    cur = Path()
    for part in rel.parts:
        cur = cur / part
        if _budget_tree(list(cur.parts)):
            return True
    return False


def plan_oldest_first(objects: list[dict], cap: int) -> dict:
    ordered = sorted(objects, key=lambda o: (o["order_key"], str(o["path"])))
    total = sum(int(o["bytes"]) for o in ordered)
    if total <= cap:
        return {"drop": [], "drop_bytes": 0, "keep_bytes": total}
    drop = []
    dropped = 0
    remaining = len(ordered)
    for obj in ordered:
        if total - dropped <= cap:
            break
        if remaining <= 1:
            break
        drop.append(obj)
        dropped += int(obj["bytes"])
        remaining -= 1
    return {"drop": drop, "drop_bytes": dropped, "keep_bytes": total - dropped}


def apply_plan(root: Path, plan: dict) -> int:
    deleted = 0
    root_res = root.resolve()
    for obj in plan["drop"]:
        path: Path = obj["path"]
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if root_res not in resolved.parents and root not in path.parents and resolved != root_res:
            if not str(resolved).startswith(str(root_res)):
                continue
        size = path.stat().st_size
        path.unlink()
        deleted += size
        _prune_empty(path, root)
    return deleted


def _prune_empty(file_path: Path, root: Path) -> None:
    cur = file_path.parent
    while cur != root and root in cur.parents:
        try:
            next(cur.iterdir())
            return
        except StopIteration:
            cur.rmdir()
            cur = cur.parent
        except OSError:
            return


def decision_exit(decision: str) -> int:
    return {
        "proceed": EXIT_PROCEED,
        "skip_backup": EXIT_SKIP,
        "prune_then_backup": EXIT_PRUNE,
        "fail_closed": EXIT_FAIL,
    }[decision]


def run_self_test() -> int:
    gib = GIB
    base = {
        "disk_total_bytes": 200 * gib,
        "disk_free_bytes": 80 * gib,
        "backup_bytes": 40 * gib,
        "reserved_free_percent": 10,
        "bytes_over_budget": 0,
        "operator_requested_backup": False,
        "test_deploy": False,
        "backup_required": False,
    }

    def case(**overrides):
        merged = dict(base)
        merged.update(overrides)
        return preflight_update(merged)

    assert case(test_deploy=True)["decision"] == "skip_backup"
    assert case(test_deploy=True, operator_requested_backup=True)["decision"] == "proceed"
    assert case(test_deploy=True, disk_free_bytes=1 * gib)["decision"] == "fail_closed"
    assert (
        case(
            disk_free_bytes=30 * gib,
            backup_bytes=90 * gib,
            operator_requested_backup=True,
        )["decision"]
        == "skip_backup"
    )
    assert (
        case(
            disk_free_bytes=30 * gib,
            backup_bytes=90 * gib,
            operator_requested_backup=True,
            backup_required=True,
        )["decision"]
        == "fail_closed"
    )
    prune = case(
        disk_free_bytes=20 * gib,
        backup_bytes=50 * gib,
        bytes_over_budget=60 * gib,
        operator_requested_backup=True,
    )
    assert prune == {"decision": "prune_then_backup", "reclaim_bytes": 60 * gib}
    assert case(operator_requested_backup=True)["decision"] == "proceed"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = root / "history/building_id=site-a/equipment_id=ahu/year=2024/month=01/part-20240101T000000Z-live.parquet"
        new = root / "history/building_id=site-a/equipment_id=ahu/year=2026/month=06/part-20260601T000000Z-live.parquet"
        analytics = root / "analytics_results/building_id=site-a/query_id=runtime/part-20240102T000000Z.parquet"
        archive = root / "archives/keep.parquet"
        for path in (old, new, analytics, archive):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 32)
        objects = collect_objects(root)
        assert len(objects) == 3, [str(o["path"]) for o in objects]
        plan = plan_oldest_first(objects, 40)
        apply_plan(root, plan)
        assert not old.exists()
        assert not analytics.exists()
        assert new.exists()
        assert archive.exists()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        decoy = root / "equipment_id=AHU_1/part-20240101T000000Z.parquet"
        nested = root / "notes/equipment_id=building=site-a/part-20240101T000000Z.parquet"
        hive = root / "building=site-a/part-20260601T000000Z.parquet"
        for path in (decoy, nested, hive):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 8)
        found = {item["path"] for item in collect_objects(root)}
        assert found == {hive}
        assert not legacy_building_hive_segment("equipment_id=AHU_1")
        assert not legacy_building_hive_segment("building_id=site-a")
        assert legacy_building_hive_segment("building=site-a")
    print("openfdd_disk_preflight self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--storage-root", default="")
    parser.add_argument("--backup-bytes", type=int, default=None)
    parser.add_argument("--full-copy", action="store_true", help="backup size = live parquet bytes")
    parser.add_argument(
        "--metadata-snapshot",
        action="store_true",
        help="backup size is a small tag/env snapshot, not a second historian",
    )
    parser.add_argument("--test-deploy", action="store_true")
    parser.add_argument("--operator-requested-backup", action="store_true")
    parser.add_argument("--backup-required", action="store_true")
    parser.add_argument("--apply-prune", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()

    root = Path(args.storage_root or os.environ.get("OPENFDD_PARQUET_ROOT") or ".").resolve()
    if not root.exists():
        print(f"ERROR: storage root does not exist: {root}", file=sys.stderr)
        return 2
    usage = shutil.disk_usage(root)
    enabled = budget_enabled()
    cap = budget_bytes()
    objects = collect_objects(root) if enabled else []
    used = sum(int(o["bytes"]) for o in objects)
    over = max(0, used - cap) if enabled else 0
    if args.backup_bytes is not None:
        backup = args.backup_bytes
    elif args.metadata_snapshot:
        backup = METADATA_SNAPSHOT_BYTES
    elif args.full_copy:
        backup = used
    else:
        backup = used
    test_deploy = args.test_deploy or env_truthy(os.environ.get("OPENFDD_TEST_DEPLOY"))
    asked = args.operator_requested_backup or env_truthy(os.environ.get("OPENFDD_BACKUP_ON_UPDATE"))
    decision = preflight_update(
        {
            "disk_total_bytes": usage.total,
            "disk_free_bytes": usage.free,
            "backup_bytes": backup,
            "reserved_free_percent": reserved_percent(),
            "bytes_over_budget": over,
            "operator_requested_backup": asked,
            "test_deploy": test_deploy,
            "backup_required": args.backup_required,
        }
    )
    pruned = 0
    if args.apply_prune and decision["decision"] == "prune_then_backup" and enabled:
        plan = plan_oldest_first(objects, cap)
        pruned = apply_plan(root, plan)
    payload = {
        "ok": decision["decision"] != "fail_closed",
        "decision": decision["decision"],
        "reason": decision.get("reason", ""),
        "reclaim_bytes": decision.get("reclaim_bytes", 0),
        "pruned_bytes": pruned,
        "budget_enabled": enabled,
        "budget_bytes": cap,
        "used_bytes": used,
        "bytes_over_budget": over,
        "backup_bytes": backup,
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "storage_root": str(root),
        "test_deploy": test_deploy,
        "operator_requested_backup": asked,
    }
    if args.json or not sys.stdout.isatty():
        print(json.dumps(payload))
    else:
        print(
            f"decision={payload['decision']} over={over} backup={backup} free={usage.free} pruned={pruned}"
        )
        if payload["reason"]:
            print(payload["reason"])
    return decision_exit(decision["decision"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"self-test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
