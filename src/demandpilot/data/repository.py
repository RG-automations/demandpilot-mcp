"""Read-only, parameterized queries over the demo database. No forecasting here."""

from __future__ import annotations

import sqlite3

from demandpilot.models import DatasetMetadata, InventorySnapshot, Product, SalesRecord


def get_dataset_metadata(conn: sqlite3.Connection) -> DatasetMetadata:
    row = conn.execute(
        "SELECT is_synthetic, seed, reference_date, generator_version FROM dataset_metadata"
    ).fetchone()
    if row is None:
        raise RuntimeError("dataset_metadata table is empty")
    return DatasetMetadata(
        is_synthetic=bool(row["is_synthetic"]),
        seed=row["seed"],
        reference_date=row["reference_date"],
        generator_version=row["generator_version"],
    )


def list_products(conn: sqlite3.Connection) -> list[Product]:
    rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
    return [_row_to_product(r) for r in rows]


def get_product(conn: sqlite3.Connection, sku: str) -> Product | None:
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    return _row_to_product(row) if row is not None else None


def get_sales_history(
    conn: sqlite3.Connection, sku: str, reference_date: str, days: int
) -> list[SalesRecord]:
    """Returns up to `days` most recent sales records strictly before reference_date,
    ordered chronologically ascending.
    """
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT * FROM sales_history
            WHERE sku = ? AND date < ?
            ORDER BY date DESC
            LIMIT ?
        ) ORDER BY date ASC
        """,
        (sku, reference_date, days),
    ).fetchall()
    return [_row_to_sales_record(r) for r in rows]


def get_inventory(conn: sqlite3.Connection, sku: str) -> InventorySnapshot | None:
    row = conn.execute(
        "SELECT * FROM inventory WHERE sku = ? ORDER BY as_of_date DESC LIMIT 1",
        (sku,),
    ).fetchone()
    return _row_to_inventory(row) if row is not None else None


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(
        sku=row["sku"],
        product_name=row["product_name"],
        demand_profile=row["demand_profile"],
        lead_time_days=row["lead_time_days"],
        review_period_days=row["review_period_days"],
        service_level=row["service_level"],
        moq=row["moq"],
        pack_size=row["pack_size"],
    )


def _row_to_sales_record(row: sqlite3.Row) -> SalesRecord:
    return SalesRecord(
        sku=row["sku"],
        date=row["date"],
        quantity_sold=row["quantity_sold"],
        is_promotion=bool(row["is_promotion"]),
        is_stockout=bool(row["is_stockout"]),
    )


def _row_to_inventory(row: sqlite3.Row) -> InventorySnapshot:
    return InventorySnapshot(
        sku=row["sku"],
        as_of_date=row["as_of_date"],
        on_hand=row["on_hand"],
        on_order=row["on_order"],
        reserved=row["reserved"],
    )
