"""SQLite connection helpers. No business logic here."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_SQL = resources.files("demandpilot.data").joinpath("schema.sql").read_text()


def connect_rw(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-write connection, creating the file if needed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-only connection. Raises FileNotFoundError if the db is missing."""
    resolved = Path(db_path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Database not found: {resolved}")
    uri = f"file:{resolved.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
