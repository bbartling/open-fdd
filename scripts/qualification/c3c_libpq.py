"""Protected libpq credentials for disposable C3c migration clients (harness-only).

Never pass a DSN or password on ``psql`` / ``pg_dump`` argv. Use PG* env vars or
``PGPASSFILE`` populated from ``OPENFDD_TEST_DATABASE_URL`` / ``OPENFDD_DATABASE_URL``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


def pg_client_paths() -> dict[str, str | None]:
    return {name: shutil.which(name) for name in ("psql", "pg_dump")}


def missing_pg_clients() -> list[str]:
    paths = pg_client_paths()
    return sorted(name for name, path in paths.items() if not path)


def _conn_parts(database_url: str) -> dict[str, str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError("database URL must be postgresql:// or postgres://")
    dbname = (parsed.path or "").lstrip("/") or "postgres"
    out = {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": dbname,
    }
    if not out["password"]:
        out["password"] = os.environ.get("PGPASSWORD", "")
    return out


def libpq_subprocess_env(*, database_url: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess env with libpq variables; password never appears in argv."""
    env = dict(base or os.environ)
    parts = _conn_parts(database_url)
    env["PGHOST"] = parts["host"]
    env["PGPORT"] = parts["port"]
    env["PGUSER"] = parts["user"]
    env["PGDATABASE"] = parts["dbname"]
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]
    else:
        env.pop("PGPASSWORD", None)
    return env


def admin_dbname(database_url: str) -> str:
    return "postgres"


def scratch_dbname(database_url: str, *, name: str = "openfdd_c3c_scratch") -> str:
    parts = _conn_parts(database_url)
    _ = parts
    return name


def run_psql(
    *,
    database_url: str,
    dbname: str,
    args: list[str],
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    paths = pg_client_paths()
    if not paths["psql"]:
        raise FileNotFoundError("psql not found on PATH")
    env = libpq_subprocess_env(database_url=database_url)
    env["PGDATABASE"] = dbname
    cmd = [paths["psql"], "-v", "ON_ERROR_STOP=1", *args]
    return subprocess.run(
        cmd,
        check=check,
        env=env,
        text=True,
        capture_output=capture_output,
    )


def run_pg_dump(
    *,
    database_url: str,
    dbname: str,
    extra_args: list[str],
    check: bool = True,
) -> bytes:
    paths = pg_client_paths()
    if not paths["pg_dump"]:
        raise FileNotFoundError("pg_dump not found on PATH")
    env = libpq_subprocess_env(database_url=database_url)
    env["PGDATABASE"] = dbname
    cmd = [paths["pg_dump"], *extra_args]
    return subprocess.check_output(cmd, env=env)


def with_dbname(database_url: str, dbname: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


def blocked_migration_client_receipt(*, missing: list[str]) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "missing_clients": missing,
        "reason": "host psql/pg_dump required for SQL-QUAL-12A throwaway restore proof",
        "restore_target": "owned throwaway database only (openfdd_c3c_scratch)",
    }
