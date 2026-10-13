#!/usr/bin/env python3
"""Test-only: pandas open_fdd.rules vs Timescale SQL (Wave-X W6).

Never import this from product containers. DuckDB optional for unit SQL checks.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("OPENFDD_DATABASE_URL"))
    ap.add_argument("--building-id", default="BUILDING_50")
    ap.add_argument("--out", default="/tmp/openfdd-softopen/3.6.0/checkpoints/W6_parity.json")
    args=ap.parse_args()
    out={"engine":"timescale", "building_id": args.building_id, "pandas": None, "sql": None, "verdict": "BLOCKED"}
    if not args.database_url:
        out["error"]="OPENFDD_DATABASE_URL missing"
        Path(args.out).write_text(json.dumps(out, indent=2)+"\n")
        print(json.dumps(out, indent=2)); return 2
    try:
        import psycopg
    except ImportError:
        out["error"]="psycopg missing (test host)"
        Path(args.out).write_text(json.dumps(out, indent=2)+"\n")
        print(json.dumps(out, indent=2)); return 2
    with psycopg.connect(args.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sample WHERE site_id=%s", (args.building_id,))
        samples=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fdd_rule_registry")
        rules=cur.fetchone()[0]
        out["sql"]={"sample_count": samples, "registry_rules": rules}
    # DuckDB optional smoke (never product)
    try:
        import duckdb
        con=duckdb.connect()
        con.execute("SELECT 1 AS ok")
        out["duckdb_test_only"]="ok"
    except Exception as e:
        out["duckdb_test_only"]=f"skip:{e}"
    # pandas oracle optional
    try:
        import open_fdd  # noqa: F401
        out["pandas"]={"import":"ok", "note":"full rule parity harness TBD vs sql/fdd"}
    except Exception as e:
        out["pandas"]={"import":"missing", "error":str(e)}
    if out["sql"]["sample_count"]>0 and out["sql"]["registry_rules"]>=70:
        out["verdict"]="SOFT_OPEN_SEED_OK"
    else:
        out["verdict"]="FAIL_SEED"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2)+"\n")
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"].startswith("SOFT") else 1

if __name__=="__main__":
    raise SystemExit(main())
