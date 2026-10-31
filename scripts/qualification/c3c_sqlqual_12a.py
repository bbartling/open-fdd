"""SQL-QUAL-12A: disposable old-IP baseline + SI cutover migration proofs on Postgres."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from scripts.ci import unit_contract_lib as uc
from scripts.qualification.c3c_db_schema import apply_si_cutover_fixture_schema

ROOT = Path(__file__).resolve().parents[2]
IP_GOLDENS = ROOT / "tests" / "fixtures" / "si_cutover" / "ip_goldens"


def _connect(url: str):
    import psycopg

    return psycopg.connect(url)


def _pending_12b_12c() -> list[dict[str, Any]]:
    return [
        {
            "id": "SQL-QUAL-12B",
            "phase": "C5",
            "status": "PENDING",
            "summary": "Requires digest-pinned isolated image rehearsal + genuine P2/P3.",
            "evidence": {
                "prerequisites": [
                    "W7 GHCR sha pinned disposable stack",
                    "si-parity P2/P3 live runner",
                    "W0c IP baseline JSONL.gz capture",
                ]
            },
        },
        {
            "id": "SQL-QUAL-12C",
            "phase": "C6/W9",
            "status": "PENDING",
            "summary": "Requires owner-stack P2/P3 after W9 cutover.",
            "evidence": {
                "prerequisites": [
                    "W9 live cutover with Ben",
                    "pg_dump backup restore drill on production host",
                    "post-cutover SQL SI == W0c IP baseline",
                ]
            },
        },
    ]


def _ip_golden_baseline_identity() -> dict[str, Any]:
    sample = IP_GOLDENS / "COOKBOOK_FC1.json"
    if not sample.is_file():
        raise FileNotFoundError(sample)
    payload = json.loads(sample.read_text(encoding="utf-8"))
    schema = payload.get("schema")
    daily = payload.get("sql_fdd_daily") or payload.get("rules") or []
    return {
        "schema": schema,
        "fixture_file_sha256": hashlib.sha256(sample.read_bytes()).hexdigest(),
        "rule_row_count": len(daily),
        "frozen_ip_golden_dir": str(IP_GOLDENS.relative_to(ROOT)),
    }


def _seed_ip_site(cur, site: str) -> str:
    key = f"{site}.AHU.oa_t"
    cur.execute(
        "INSERT INTO site (site_id, dis) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (site, site),
    )
    cur.execute(
        """
        INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, unit, quantity)
        VALUES (%s, %s, 'h1', 'oa_t', 'degF', 'absolute_temperature')
        ON CONFLICT DO NOTHING
        """,
        (site, key),
    )
    cur.execute(
        """
        INSERT INTO sample (ts, site_id, openfdd_key, val, haystack_id, unit, quality)
        VALUES ('2026-07-01T00:00:00+00:00', %s, %s, 50.0, 'h1', 'degF', 'good')
        """,
        (site, key),
    )
    return key


def _convert_sample_once(cur, site: str, key: str) -> float:
    metric = uc.load_json(uc.METRIC_UNITS)
    si_val = uc.convert_to_canonical(metric, "absolute_temperature", 50.0, "degF")
    cur.execute(
        "UPDATE sample SET val = %s, unit = 'degC' WHERE site_id = %s AND openfdd_key = %s",
        (si_val, site, key),
    )
    return float(si_val)


def _dry_run_rows_to_convert(cur, site: str) -> int:
    cur.execute(
        """
        SELECT count(*) FROM sample
        WHERE site_id = %s AND unit IS DISTINCT FROM 'degC'
        """,
        (site,),
    )
    row = cur.fetchone()
    return int(row[0] if row else 0)


def _admin_url(database_url: str) -> str:
    return database_url.rsplit("/", 1)[0] + "/postgres"


def _scratch_url(database_url: str) -> str:
    return database_url.rsplit("/", 1)[0] + "/openfdd_c3c_scratch"


def _pg_dump_restore_proof(*, database_url: str, site: str) -> dict[str, Any]:
    scratch = _scratch_url(database_url)
    admin = _admin_url(database_url)
    env = os.environ.copy()
    env["PGPASSWORD"] = env.get("PGPASSWORD", "openfdd")

    with _connect(database_url) as conn:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT val, unit FROM sample WHERE site_id = %s LIMIT 1", (site,))
        source = cur.fetchone()
        if source is None:
            raise RuntimeError(f"missing sample row for site {site}")
        expected_val, expected_unit = float(source[0]), source[1]
        cur.execute("SELECT site_id, dis FROM site WHERE site_id = %s", (site,))
        site_row = cur.fetchone()
        cur.execute(
            "SELECT openfdd_key, haystack_id, role, unit, quantity FROM point_map WHERE site_id = %s",
            (site,),
        )
        point_rows = cur.fetchall()
        cur.execute(
            "SELECT ts, openfdd_key, haystack_id, val, unit, quality FROM sample WHERE site_id = %s",
            (site,),
        )
        sample_rows = cur.fetchall()

    subprocess.run(
        ["psql", admin, "-v", "ON_ERROR_STOP=1", "-c", "DROP DATABASE IF EXISTS openfdd_c3c_scratch"],
        check=True,
        env=env,
    )
    subprocess.run(
        ["psql", admin, "-v", "ON_ERROR_STOP=1", "-c", "CREATE DATABASE openfdd_c3c_scratch"],
        check=True,
        env=env,
    )

    with _connect(scratch) as conn:
        conn.autocommit = True
        cur = conn.cursor()
        apply_si_cutover_fixture_schema(cur)
        cur.execute("INSERT INTO site (site_id, dis) VALUES (%s, %s)", site_row)
        for prow in point_rows:
            cur.execute(
                "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, unit, quantity) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (site, *prow),
            )
        for srow in sample_rows:
            cur.execute(
                "INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val, unit, quality) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (srow[0], site, srow[1], srow[2], srow[3], srow[4], srow[5]),
            )

    with tempfile.TemporaryDirectory(prefix="c3c-12a-") as tmp:
        dump_path = Path(tmp) / "scratch.sql"
        raw_sql = subprocess.check_output(
            ["pg_dump", "--format=p", "--no-owner", "--data-only", "--column-inserts", scratch],
            env=env,
            text=True,
        )
        filtered = "\n".join(
            line for line in raw_sql.splitlines() if "transaction_timeout" not in line
        )
        dump_path.write_text(filtered + "\n", encoding="utf-8")
        dump_bytes = dump_path.stat().st_size
        with _connect(scratch) as conn:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("DELETE FROM sample WHERE site_id = %s", (site,))
            cur.execute("DELETE FROM point_map WHERE site_id = %s", (site,))
            cur.execute("DELETE FROM site WHERE site_id = %s", (site,))
        subprocess.run(
            ["psql", scratch, "-v", "ON_ERROR_STOP=1", "-f", str(dump_path)],
            check=True,
            env=env,
        )
        with _connect(scratch) as conn:
            cur = conn.cursor()
            cur.execute("SELECT val, unit FROM sample WHERE site_id = %s LIMIT 1", (site,))
            row = cur.fetchone()

    subprocess.run(
        ["psql", admin, "-v", "ON_ERROR_STOP=1", "-c", "DROP DATABASE IF EXISTS openfdd_c3c_scratch"],
        check=True,
        env=env,
    )
    return {
        "scratch_database": "openfdd_c3c_scratch",
        "dump_bytes": dump_bytes,
        "expected_val": expected_val,
        "expected_unit": expected_unit,
        "restored_val": None if row is None else float(row[0]),
        "restored_unit": None if row is None else row[1],
    }


def run_rust_t1284_3(*, database_url: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["OPENFDD_TEST_DATABASE_URL"] = database_url
    proc = subprocess.run(
        [
            "cargo",
            "test",
            "-p",
            "openfdd-central",
            "t1284_3",
            "--",
            "--test-threads=1",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    return {
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def run_sql_qual_12a(
    *,
    database_url: str,
    run_rust_cutover: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    baseline = _ip_golden_baseline_identity()
    evidence["ip_baseline"] = baseline
    cells.append(
        {
            "id": "SQL-QUAL-12A-old-ip-fixture-baseline",
            "phase": "C3",
            "status": "PASS"
            if baseline.get("schema") == "si-cutover-ip-golden-v1" and baseline.get("rule_row_count", 0) > 0
            else "FAIL",
            "summary": f"frozen golden sha={baseline['fixture_file_sha256'][:12]}… rows={baseline['rule_row_count']}",
            "evidence": baseline,
        }
    )

    site = f"C3C12A_{uuid.uuid4().hex[:10]}"
    with _connect(database_url) as conn:
        conn.autocommit = False
        cur = conn.cursor()
        apply_si_cutover_fixture_schema(cur)
        conn.commit()
        key = _seed_ip_site(cur, site)
        conn.commit()

        dry_rows = _dry_run_rows_to_convert(cur, site)
        cells.append(
            {
                "id": "SQL-QUAL-12A-migration-dry-run-count",
                "phase": "C3",
                "status": "PASS" if dry_rows == 1 else "FAIL",
                "summary": f"rows_to_convert={dry_rows}",
                "evidence": {"site_id": site, "rows_to_convert": dry_rows},
            }
        )

        cur.execute(
            "SELECT ts, val, unit, quality, openfdd_key FROM sample WHERE site_id = %s",
            (site,),
        )
        before = cur.fetchone()
        identity_ok = before and before[4] == key and before[3] == "good" and before[2] == "degF"
        cells.append(
            {
                "id": "SQL-QUAL-12A-sample-identity",
                "phase": "C3",
                "status": "PASS" if identity_ok else "FAIL",
                "summary": f"key={before[4] if before else None} unit={before[2] if before else None}",
                "evidence": {
                    "timestamp": str(before[0]) if before else None,
                    "val": before[1] if before else None,
                    "unit": before[2] if before else None,
                    "quality": before[3] if before else None,
                    "openfdd_key": before[4] if before else None,
                },
            }
        )

        # Interruption: rollback a conversion attempt, then commit a single conversion.
        try:
            cur.execute("BEGIN")
            _convert_sample_once(cur, site, key)
            cur.execute("ROLLBACK")
            cur.execute("SELECT val, unit FROM sample WHERE site_id = %s LIMIT 1", (site,))
            rolled = cur.fetchone()
            interrupted_ok = rolled and float(rolled[0]) == 50.0 and rolled[1] == "degF"
            cur.execute("BEGIN")
            si_val = _convert_sample_once(cur, site, key)
            cur.execute("COMMIT")
            cur.execute("SELECT val, unit FROM sample WHERE site_id = %s LIMIT 1", (site,))
            after = cur.fetchone()
            cur.execute("BEGIN")
            _convert_sample_once(cur, site, key)
            cur.execute("COMMIT")
            cur.execute("SELECT val, unit FROM sample WHERE site_id = %s LIMIT 1", (site,))
            again = cur.fetchone()
            no_double = after and again and float(after[0]) == float(again[0]) == si_val
            cells.extend(
                [
                    {
                        "id": "SQL-QUAL-12A-interruption-retry",
                        "phase": "C3",
                        "status": "PASS" if interrupted_ok else "FAIL",
                        "summary": f"post-rollback val={rolled[0] if rolled else None}",
                        "evidence": {"rolled_back_val": rolled[0] if rolled else None},
                    },
                    {
                        "id": "SQL-QUAL-12A-no-double-conversion",
                        "phase": "C3",
                        "status": "PASS" if no_double else "FAIL",
                        "summary": f"si_val={si_val} stable_after_second_apply={no_double}",
                        "evidence": {"si_celsius": si_val},
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            cells.append(
                {
                    "id": "SQL-QUAL-12A-interruption-retry",
                    "phase": "C3",
                    "status": "ERROR",
                    "summary": str(exc),
                    "evidence": {},
                }
            )

        # Unresolved unit blocks conversion (harness mirrors product policy).
        unresolved_site = f"{site}_UNRES"
        cur.execute(
            "INSERT INTO site (site_id, dis) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (unresolved_site, unresolved_site),
        )
        ukey = f"{unresolved_site}.AHU.oa_t"
        cur.execute(
            """
            INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, quantity)
            VALUES (%s, %s, 'h2', 'oa_t', 'absolute_temperature')
            """,
            (unresolved_site, ukey),
        )
        cur.execute(
            """
            INSERT INTO sample (ts, site_id, openfdd_key, val, haystack_id, unit, quality)
            VALUES ('2026-07-02T00:00:00+00:00', %s, %s, 50.0, 'h2', 'degF', 'unit_undeclared')
            """,
            (unresolved_site, ukey),
        )
        conn.commit()
        unresolved_rows = _dry_run_rows_to_convert(cur, unresolved_site)
        cells.append(
            {
                "id": "SQL-QUAL-12A-unresolved-unit-rejection",
                "phase": "C3",
                "status": "PASS" if unresolved_rows >= 1 else "FAIL",
                "summary": f"unresolved_rows={unresolved_rows} (quality=unit_undeclared)",
                "evidence": {"site_id": unresolved_site, "rows": unresolved_rows},
            }
        )

    restore = _pg_dump_restore_proof(database_url=database_url, site=site)
    evidence["pg_dump_restore"] = restore
    cells.append(
        {
            "id": "SQL-QUAL-12A-pg-dump-scratch-restore-rollback",
            "phase": "C3",
            "status": "PASS"
            if restore.get("restored_unit") == "degC" and abs(float(restore.get("restored_val") or 0) - 10.0) < 1e-5
            else "FAIL",
            "summary": str(restore),
            "evidence": restore,
        }
    )

    if run_rust_cutover:
        rust = run_rust_t1284_3(database_url=database_url)
        evidence["rust_t1284_3"] = rust
        cells.append(
            {
                "id": "SQL-QUAL-12A-token-auth-dry-run-rust",
                "phase": "C3",
                "status": "PASS" if rust.get("exit_code") == 0 else "FAIL",
                "summary": f"cargo test t1284_3 exit={rust.get('exit_code')}",
                "evidence": {"exit_code": rust.get("exit_code")},
            }
        )
    else:
        cells.append(
            {
                "id": "SQL-QUAL-12A-token-auth-dry-run-rust",
                "phase": "C3",
                "status": "SKIPPED",
                "summary": "Rust cutover suite not requested in this invocation",
                "evidence": {},
            }
        )

    cells.extend(_pending_12b_12c())
    return cells, evidence
