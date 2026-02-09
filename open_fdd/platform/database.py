"""Database connection and session."""
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from open_fdd.platform.config import get_platform_settings


@contextmanager
def get_conn():
    """Yield a DB connection with dict cursor."""
    settings = get_platform_settings()
    conn = psycopg2.connect(settings.db_dsn, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()
