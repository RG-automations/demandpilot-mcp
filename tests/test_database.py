from __future__ import annotations

import sqlite3

import pytest

from demandpilot.data import repository
from demandpilot.data.database import connect_ro


def test_connect_ro_raises_if_missing(tmp_path):
    missing = tmp_path / "nope.sqlite3"
    with pytest.raises(FileNotFoundError):
        connect_ro(missing)


def test_connect_ro_connection_rejects_writes(demo_db_path):
    conn = connect_ro(demo_db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO products VALUES ('X', 'x', 'stable', 1, 1, 0.9, 0, 1)")
    finally:
        conn.close()


def test_get_product_known_and_unknown_sku(demo_conn):
    known = repository.get_product(demo_conn, "DEMO-001")
    assert known is not None
    assert known.sku == "DEMO-001"
    assert repository.get_product(demo_conn, "DEMO-999") is None


def test_get_sales_history_orders_ascending_and_respects_days(demo_conn):
    rows = repository.get_sales_history(demo_conn, "DEMO-001", "2026-01-01", 30)
    assert len(rows) <= 30
    dates = [r.date for r in rows]
    assert dates == sorted(dates)
    assert all(d < "2026-01-01" for d in dates)


def test_get_inventory_returns_snapshot(demo_conn):
    snap = repository.get_inventory(demo_conn, "DEMO-001")
    assert snap is not None
    assert snap.sku == "DEMO-001"
    assert snap.inventory_position == snap.on_hand + snap.on_order - snap.reserved


def test_get_dataset_metadata(demo_conn):
    meta = repository.get_dataset_metadata(demo_conn)
    assert meta.is_synthetic is True
    assert meta.seed == 42
    assert meta.reference_date == "2026-01-01"
