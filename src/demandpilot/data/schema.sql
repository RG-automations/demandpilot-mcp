-- DemandPilot MCP demo database schema.
-- All data is synthetic. See data_gen.py for population logic.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    sku               TEXT PRIMARY KEY,
    product_name      TEXT NOT NULL,
    demand_profile     TEXT NOT NULL,
    lead_time_days     INTEGER NOT NULL CHECK (lead_time_days >= 0),
    review_period_days INTEGER NOT NULL CHECK (review_period_days >= 0),
    service_level      REAL NOT NULL CHECK (service_level > 0 AND service_level < 1),
    moq                INTEGER NOT NULL CHECK (moq >= 0),
    pack_size          INTEGER NOT NULL CHECK (pack_size > 0)
);

CREATE TABLE IF NOT EXISTS sales_history (
    sku            TEXT NOT NULL REFERENCES products(sku),
    date           TEXT NOT NULL,
    quantity_sold  INTEGER NOT NULL CHECK (quantity_sold >= 0),
    is_promotion   INTEGER NOT NULL CHECK (is_promotion IN (0, 1)),
    is_stockout    INTEGER NOT NULL CHECK (is_stockout IN (0, 1)),
    PRIMARY KEY (sku, date)
);

CREATE TABLE IF NOT EXISTS inventory (
    sku         TEXT NOT NULL REFERENCES products(sku),
    as_of_date  TEXT NOT NULL,
    on_hand     INTEGER NOT NULL CHECK (on_hand >= 0),
    on_order    INTEGER NOT NULL CHECK (on_order >= 0),
    reserved    INTEGER NOT NULL CHECK (reserved >= 0),
    PRIMARY KEY (sku, as_of_date)
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    is_synthetic      INTEGER NOT NULL CHECK (is_synthetic IN (0, 1)),
    seed              INTEGER NOT NULL,
    reference_date    TEXT NOT NULL,
    generator_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_history_sku_date ON sales_history (sku, date);
