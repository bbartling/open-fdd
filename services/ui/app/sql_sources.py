"""Read-only SQL sources → pandas (SQLite, DuckDB, optional SQL Server)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd

from app.data_loader import normalize_timestamp

UNSAFE_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|merge|create|exec|execute|attach|grant|revoke)\b",
    re.I,
)


def validate_readonly_sql(query: str) -> None:
    q = query.strip()
    if not re.match(r"^\s*select\b", q, re.I):
        raise ValueError("Only read-only SELECT queries are allowed")
    if UNSAFE_SQL.search(q):
        raise ValueError("Destructive or DDL SQL keywords are not allowed")


def load_sqlite_table(db_path: Path | str, table: str, *, row_limit: int | None = None) -> pd.DataFrame:
    import sqlite3

    limit = f" LIMIT {int(row_limit)}" if row_limit else ""
    validate_readonly_sql(f"SELECT * FROM {table}{limit}")
    con = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table}"{limit}', con)
    finally:
        con.close()
    return normalize_timestamp(df)


def load_duckdb_query(db_path: Path | str, query: str) -> pd.DataFrame:
    import duckdb

    validate_readonly_sql(query)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(query).df()
    finally:
        con.close()
    return normalize_timestamp(df)


@dataclass
class SqlServerConfig:
    server: str
    database: str
    username: str = ""
    password: str = ""
    trusted_connection: bool = False
    driver: str = "ODBC Driver 18 for SQL Server"
    row_limit: int = 50000

    def masked(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "database": self.database,
            "username": self.username,
            "trusted_connection": self.trusted_connection,
            "driver": self.driver,
            "row_limit": self.row_limit,
            "password": "****" if self.password else "",
        }


def sqlserver_available() -> bool:
    try:
        import sqlalchemy  # noqa: F401
        import pyodbc  # noqa: F401

        return True
    except ImportError:
        return False


def build_sqlserver_url(cfg: SqlServerConfig) -> str:
    if cfg.trusted_connection:
        odbc = (
            f"DRIVER={{{cfg.driver}}};SERVER={cfg.server};DATABASE={cfg.database};"
            "Trusted_Connection=yes;TrustServerCertificate=yes;"
        )
    else:
        odbc = (
            f"DRIVER={{{cfg.driver}}};SERVER={cfg.server};DATABASE={cfg.database};"
            f"UID={cfg.username};PWD={cfg.password};TrustServerCertificate=yes;"
        )
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}"


def load_sqlserver_query(cfg: SqlServerConfig, query: str) -> pd.DataFrame:
    if not sqlserver_available():
        raise ImportError(
            "SQL Server support requires: pip install sqlalchemy pyodbc "
            "(and Microsoft ODBC Driver 18 for SQL Server on the host)"
        )
    validate_readonly_sql(query)
    from sqlalchemy import create_engine, text

    q = query.strip().rstrip(";")
    if cfg.row_limit and "limit" not in q.lower() and "top " not in q.lower():
        q = f"SELECT TOP {cfg.row_limit} * FROM ({q}) AS _sub"
    engine = create_engine(build_sqlserver_url(cfg))
    with engine.connect() as conn:
        df = pd.read_sql(text(q), conn)
    return normalize_timestamp(df)


def config_from_streamlit_secrets(section: str = "sqlserver") -> SqlServerConfig | None:
    try:
        import streamlit as st

        sec = st.secrets.get(section)
        if not sec:
            return None
        return SqlServerConfig(
            server=str(sec.get("server", "")),
            database=str(sec.get("database", "")),
            username=str(sec.get("username", "")),
            password=str(sec.get("password", "")),
            trusted_connection=bool(sec.get("trusted_connection", False)),
            driver=str(sec.get("driver", "ODBC Driver 18 for SQL Server")),
            row_limit=int(sec.get("row_limit", 50000)),
        )
    except Exception:
        return None
