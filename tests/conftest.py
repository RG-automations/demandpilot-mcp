from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from demandpilot.data.database import connect_ro
from demandpilot.data_gen import write_database

SEED = 42
REFERENCE_DATE = date(2026, 1, 1)
SKU_COUNT = 20
HISTORY_DAYS = 730


@pytest.fixture(scope="session")
def demo_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("db") / "demo.sqlite3"
    write_database(db_path, SEED, REFERENCE_DATE, SKU_COUNT, HISTORY_DAYS)
    return db_path


@pytest.fixture()
def demo_conn(demo_db_path: Path):
    conn = connect_ro(demo_db_path)
    try:
        yield conn
    finally:
        conn.close()
