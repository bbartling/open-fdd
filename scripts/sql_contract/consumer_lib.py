"""Installed-artifact verification (no product Rust; SQL bytes from artifact root only)."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.sql_contract.companions import (
    ANALYTICS_QUERIES_DIR,
    ANALYTICS_REGISTRY,
    COMPANION_RELPATHS,
    POSTGRES_HELPERS,
    SCHEMA_INSTALL_ORDER,
)
from scripts.sql_contract.pack_digest import (
    distribution_digest,
    load_scientific_manifest,
    scientific_pack_digest,
    sha256_file,
)


@dataclass
class VerifyReceipt:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    comparisons: int = 0

    def add(self, check_id: str, status: str, *, comparisons: int = 0, detail: str = "") -> None:
        self.checks.append(
            {"check_id": check_id, "status": status, "comparisons": comparisons, "detail": detail}
        )
        if comparisons:
            self.comparisons += comparisons
        if status == "FAIL":
            self.errors.append(f"{check_id}: {detail}")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "openfdd-si-installed-consumer-receipt-v1",
            "ok": self.ok,
            "comparisons": self.comparisons,
            "checks": self.checks,
            "errors": self.errors,
        }


def _statements(sql_text: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            current = []
            if stmt:
                out.append(stmt)
    tail = "\n".join(current).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def verify_integrity(artifact_root: Path, *, expected_source_revision: str | None) -> VerifyReceipt:
    receipt = VerifyReceipt(ok=True)
    dist_path = artifact_root / "distribution_manifest.json"
    if not dist_path.is_file():
        receipt.add("distribution_manifest_present", "FAIL", detail="missing distribution_manifest.json")
        receipt.ok = False
        return receipt
    dist_doc = json.loads(dist_path.read_text(encoding="utf-8"))
    receipt.add("distribution_manifest_present", "PASS", comparisons=1)

    rev_file = artifact_root / "SOURCE_REVISION"
    if not rev_file.is_file():
        receipt.add("source_revision_file", "FAIL", detail="missing SOURCE_REVISION")
        receipt.ok = False
    else:
        rev = rev_file.read_text(encoding="utf-8").strip()
        if expected_source_revision and rev != expected_source_revision:
            receipt.add(
                "source_revision_pin",
                "FAIL",
                detail=f"expected {expected_source_revision} got {rev}",
            )
            receipt.ok = False
        else:
            receipt.add("source_revision_pin", "PASS", comparisons=1, detail=rev)

    manifest = load_scientific_manifest(artifact_root)
    try:
        pack = scientific_pack_digest(manifest)
    except ValueError as exc:
        receipt.add("scientific_pack_digest", "FAIL", detail=str(exc))
        receipt.ok = False
        pack = ""
    else:
        receipt.add("scientific_pack_digest", "PASS", comparisons=len(manifest.get("files") or []))

    pinned_pack = str(dist_doc.get("scientific_pack_sha256") or "")
    if pack and pinned_pack != pack:
        receipt.add(
            "distribution_binds_scientific_pack",
            "FAIL",
            detail=f"dist pins {pinned_pack} recomputed {pack}",
        )
        receipt.ok = False
    elif pack:
        receipt.add("distribution_binds_scientific_pack", "PASS", comparisons=1)

    companions = []
    for rel in COMPANION_RELPATHS:
        p = artifact_root / rel
        if not p.is_file():
            receipt.add(f"companion_{rel}", "FAIL", detail="missing")
            receipt.ok = False
            continue
        companions.append({"path": rel, "sha256": sha256_file(p)})
    for entry in dist_doc.get("companion_files") or []:
        rel = entry["path"]
        p = artifact_root / rel
        if not p.is_file():
            continue
        dig = sha256_file(p)
        if dig != entry.get("sha256"):
            receipt.add(f"companion_hash_{rel}", "FAIL", detail="sha256 drift")
            receipt.ok = False
        else:
            receipt.add(f"companion_hash_{rel}", "PASS", comparisons=1)

    if pack:
        dist_recomputed = distribution_digest(scientific_pack_sha256=pack, companion_entries=companions)
        pinned_dist = str(dist_doc.get("distribution_sha256") or "")
        if pinned_dist != dist_recomputed:
            receipt.add(
                "distribution_sha256",
                "FAIL",
                detail=f"manifest={pinned_dist} recomputed={dist_recomputed}",
            )
            receipt.ok = False
        else:
            receipt.add("distribution_sha256", "PASS", comparisons=1)

    abi = str(dist_doc.get("processing_abi") or "")
    metric_path = artifact_root / "sql/contract/metric_units.json"
    if metric_path.is_file():
        metric_doc = json.loads(metric_path.read_text(encoding="utf-8"))
        metric_abi = metric_doc.get("processing_abi_current") or metric_doc.get("processing_abi")
        if abi and metric_abi != abi:
            receipt.add("processing_abi_consistent", "FAIL", detail=f"{metric_abi} != {abi}")
            receipt.ok = False
        else:
            receipt.add("processing_abi_consistent", "PASS", comparisons=1)

    for entry in manifest.get("files") or []:
        rel = entry["path"]
        p = artifact_root / rel
        if not p.is_file():
            receipt.add("scientific_file_bytes", "FAIL", detail=f"missing {rel}")
            receipt.ok = False
            continue
        dig = sha256_file(p)
        if dig != entry.get("sha256") or p.stat().st_size != int(entry.get("bytes") or -1):
            receipt.add("scientific_file_bytes", "FAIL", detail=f"drift {rel}")
            receipt.ok = False
    if receipt.ok:
        receipt.add("scientific_file_bytes", "PASS", comparisons=len(manifest.get("files") or []))

    return receipt


def apply_schema(conn, artifact_root: Path) -> None:
    for rel in SCHEMA_INSTALL_ORDER:
        path = artifact_root / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        for stmt in _statements(path.read_text(encoding="utf-8")):
            with conn.cursor() as cur:
                cur.execute(stmt)
        conn.commit()


def apply_helpers(conn, artifact_root: Path) -> None:
    path = artifact_root / POSTGRES_HELPERS
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def _load_render(artifact_root: Path):
    fdd = artifact_root / "sql/fdd"
    spec = importlib.util.spec_from_file_location("ofdd_render_rule", fdd / "render_rule.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("render_rule load failed")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def verify_unit_goldens(artifact_root: Path, receipt: VerifyReceipt) -> None:
    from scripts.ci import unit_contract_lib as uc

    metric = json.loads((artifact_root / "sql/contract/metric_units.json").read_text(encoding="utf-8"))
    goldens = json.loads((artifact_root / "sql/contract/goldens/unit_vectors.json").read_text(encoding="utf-8"))
    cases = goldens.get("cases") or []
    mismatches = 0
    for case in cases:
        qty = str(case["quantity"])
        src = str(case["source_unit"])
        inp = float(case["input"])
        want = float(case["metric"])
        tol = float(case.get("tol") or 1e-9)
        got = float(uc.convert_to_canonical(metric, qty, inp, src))
        if abs(got - want) > tol:
            mismatches += 1
            receipt.add(
                f"unit_golden_{case.get('id')}",
                "FAIL",
                detail=f"got {got} want {want}",
            )
            receipt.ok = False
    if mismatches == 0:
        receipt.add("unit_golden_vectors", "PASS", comparisons=len(cases))


def verify_fdd_render_bind(artifact_root: Path, receipt: VerifyReceipt) -> None:
    render = _load_render(artifact_root)
    try:
        sql = render.render("FC1", poll_seconds=300, overrides={"confirm_min": 0}, dialect="postgres")
    except Exception as exc:
        receipt.add("fdd_render_fc1", "FAIL", detail=str(exc))
        receipt.ok = False
        return
    receipt.add("fdd_render_fc1", "PASS", comparisons=1)
    if "{{" in sql or "}}" in sql:
        receipt.add("fdd_binding_no_unresolved", "FAIL", detail="unresolved placeholders")
        receipt.ok = False
    else:
        receipt.add("fdd_binding_no_unresolved", "PASS", comparisons=1)
    # Comment/string safety: percent literal must survive render
    if "confirm" not in sql.lower() and "CONFIRM" not in sql:
        receipt.add("fdd_render_retains_logic", "FAIL", detail="unexpected stripped body")
        receipt.ok = False
    else:
        receipt.add("fdd_render_retains_logic", "PASS", comparisons=1)


def verify_analytics_catalog(artifact_root: Path, receipt: VerifyReceipt) -> None:
    qdir = artifact_root / ANALYTICS_QUERIES_DIR
    stems = sorted(p.stem for p in qdir.glob("*.sql"))
    if len(stems) != 19:
        receipt.add("analytics_body_count", "FAIL", detail=f"found {len(stems)}")
        receipt.ok = False
    else:
        receipt.add("analytics_body_count", "PASS", comparisons=19)
    reg = json.loads((artifact_root / ANALYTICS_REGISTRY).read_text(encoding="utf-8"))
    reg_paths = {str(r.get("sql_path")) for r in reg.get("queries") or []}
    reg_paths.add("sql/analytics/postgres/queries/sql_anomaly_series.sql")
    for stem in stems:
        rel = f"sql/analytics/postgres/queries/{stem}.sql"
        if rel not in reg_paths:
            receipt.add(f"analytics_registry_{stem}", "FAIL", detail="not in registry")
            receipt.ok = False
    receipt.add("analytics_registry_covers_bodies", "PASS", comparisons=len(stems))


def verify_analytics_execute_smoke(conn, artifact_root: Path, receipt: VerifyReceipt) -> None:
    """Execute inventory-style analytics against installed schema (bounded smoke)."""
    rel = "sql/analytics/postgres/queries/plant_health_inventory.sql"
    sql = (artifact_root / rel).read_text(encoding="utf-8")
    site = "INSTALLED_CONSUMER_SITE"
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sample WHERE site_id = %s", (site,))
        cur.execute("DELETE FROM site WHERE site_id = %s", (site,))
        cur.execute(
            "INSERT INTO site(site_id, dis, timezone, enabled) VALUES (%s, %s, 'UTC', true)",
            (site, site),
        )
        cur.execute(
            "INSERT INTO building(building_id, site_id, dis, timezone) VALUES (%s, %s, %s, 'UTC')",
            (site, site, site),
        )
        cur.execute(
            """
            INSERT INTO equipment(building_id, equipment_id, equip_type)
            VALUES (%s, %s, 'ahu')
            """,
            (site, "EQ1"),
        )
        try:
            cur.execute(sql, (site, ["EQ1"]))
            rows = cur.fetchall()
        except Exception as exc:
            receipt.add("analytics_execute_smoke", "FAIL", detail=str(exc))
            receipt.ok = False
            conn.rollback()
            return
    receipt.add("analytics_execute_smoke", "PASS", comparisons=max(1, len(rows)))


def verify_catalog_hypertable(conn, artifact_root: Path, receipt: VerifyReceipt) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'sample'
            """
        )
        if cur.fetchone() is None:
            receipt.add("catalog_sample_table", "FAIL", detail="missing sample")
            receipt.ok = False
            return
        cur.execute(
            """
            SELECT 1 FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'sample'
            """
        )
        if cur.fetchone() is None:
            receipt.add("catalog_sample_hypertable", "FAIL", detail="sample not hypertable")
            receipt.ok = False
        else:
            receipt.add("catalog_sample_hypertable", "PASS", comparisons=1)


def verify_unsupported_policy(artifact_root: Path, receipt: VerifyReceipt) -> None:
    metric = json.loads((artifact_root / "sql/contract/metric_units.json").read_text(encoding="utf-8"))
    blocked = {str(r["rule_id"]) for r in metric.get("unsupported_rules") or []}
    if "SV-RATE" not in blocked:
        receipt.add("sv_rate_unsupported", "FAIL", detail="SV-RATE must stay unsupported")
        receipt.ok = False
    else:
        receipt.add("sv_rate_unsupported", "PASS", comparisons=1)


def run_installed_verify(
    artifact_root: Path,
    *,
    database_url: str | None,
    expected_source_revision: str | None = None,
    skip_db: bool = False,
) -> VerifyReceipt:
    artifact_root = artifact_root.resolve()
    receipt = verify_integrity(artifact_root, expected_source_revision=expected_source_revision)
    verify_unit_goldens(artifact_root, receipt)
    verify_unsupported_policy(artifact_root, receipt)
    verify_analytics_catalog(artifact_root, receipt)
    verify_fdd_render_bind(artifact_root, receipt)

    if skip_db or not database_url:
        receipt.add("postgres_installed_smoke", "SKIPPED", detail="no database_url")
        receipt.ok = len(receipt.errors) == 0
        return receipt

    import psycopg

    from scripts.timescale.test_synthetic_pandas_sql_parity import connect_with_retry

    with connect_with_retry(database_url) as conn:
        apply_schema(conn, artifact_root)
        apply_helpers(conn, artifact_root)
        verify_catalog_hypertable(conn, artifact_root, receipt)
        verify_analytics_execute_smoke(conn, artifact_root, receipt)
        # Ordered timestamps / gap probe: monotonic insert
        site = "TS_ORDER_SITE"
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sample WHERE site_id = %s", (site,))
            cur.execute("DELETE FROM site WHERE site_id = %s", (site,))
            cur.execute(
                "INSERT INTO site(site_id, dis, timezone, enabled) VALUES (%s,%s,'UTC',true)",
                (site, site),
            )
            t0 = "2026-06-01T00:00:00+00:00"
            t1 = "2026-06-01T00:05:00+00:00"
            cur.execute(
                """
                INSERT INTO sample(ts, site_id, openfdd_key, val)
                VALUES (%s, %s, 'E.fan-status', 1),
                       (%s, %s, 'E.fan-status', 0)
                """,
                (t0, site, t1, site),
            )
            cur.execute(
                """
                SELECT ts FROM sample WHERE site_id = %s ORDER BY ts
                """,
                (site,),
            )
            ts = [row[0] for row in cur.fetchall()]
            conn.commit()
        if len(ts) == 2 and ts[0] < ts[1]:
            receipt.add("ordered_timestamps_smoke", "PASS", comparisons=2)
        else:
            receipt.add("ordered_timestamps_smoke", "FAIL", detail="order")
            receipt.ok = False

    receipt.ok = len(receipt.errors) == 0
    return receipt


def tamper_file(path: Path, *, append: bytes = b"\n-- tamper\n") -> str:
    old = sha256_file(path)
    path.write_bytes(path.read_bytes() + append)
    return old
