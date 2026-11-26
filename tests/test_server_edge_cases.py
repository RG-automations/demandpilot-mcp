"""In-process checks for server.py edge cases the generated demo database never produces
(e.g. a product with a zero-day protection period). Not protocol tests - see
test_mcp_integration.py for real client/subprocess coverage.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from demandpilot.data.database import connect_rw, init_schema
from demandpilot.server import create_server


@pytest.fixture()
def zero_protection_period_db(tmp_path):
    db_path = tmp_path / "edge.sqlite3"
    conn = connect_rw(db_path)
    init_schema(conn)
    conn.execute(
        "INSERT INTO products VALUES ('DEMO-001', 'Zero Lead Time', 'stable', 0, 0, 0.95, 0, 1)"
    )
    for day in range(1, 31):
        conn.execute(
            "INSERT INTO sales_history VALUES ('DEMO-001', ?, 10, 0, 0)",
            (f"2025-12-{day:02d}",),
        )
    conn.execute("INSERT INTO inventory VALUES ('DEMO-001', '2026-01-01', 50, 0, 0)")
    conn.execute("INSERT INTO dataset_metadata VALUES (1, 1, '2026-01-01', 'test')")
    conn.commit()
    conn.close()
    return db_path


def test_recommend_replenishment_with_zero_protection_period_does_not_crash(
    zero_protection_period_db,
):
    server = create_server(zero_protection_period_db)

    async def go():
        return await server.call_tool("recommend_replenishment", {"sku": "DEMO-001"})

    result = asyncio.run(go())
    data = json.loads(result.content[0].text)
    assert data["protection_period_days"] == 0
    assert data["forecast_demand"] == 0.0
    assert data["safety_stock"] == 0.0
    assert data["target_level"] == 0.0
    # on_hand (50) already covers a target level of 0 -> no order.
    assert data["final_order_qty"] == 0


@pytest.fixture()
def no_sales_history_db(tmp_path):
    """A product with zero sales_history rows (not a 'no_sales' demand profile with
    observed-zero rows - genuinely no observations at all, exercising the
    insufficient_history fallback end-to-end through the MCP tools, not just the
    forecasting module directly).
    """
    db_path = tmp_path / "edge.sqlite3"
    conn = connect_rw(db_path)
    init_schema(conn)
    conn.execute(
        "INSERT INTO products VALUES ('DEMO-001', 'No History', 'stable', 7, 7, 0.95, 10, 5)"
    )
    conn.execute("INSERT INTO inventory VALUES ('DEMO-001', '2026-01-01', 50, 0, 0)")
    conn.execute("INSERT INTO dataset_metadata VALUES (1, 1, '2026-01-01', 'test')")
    conn.commit()
    conn.close()
    return db_path


def test_forecast_demand_with_no_sales_history_returns_insufficient_history(
    no_sales_history_db,
):
    server = create_server(no_sales_history_db)

    async def go():
        return await server.call_tool("forecast_demand", {"sku": "DEMO-001", "horizon_days": 14})

    result = asyncio.run(go())
    data = json.loads(result.content[0].text)
    assert data["model_used"] == "insufficient_history"
    assert data["daily_forecast"] == []
    assert data["total_forecast_demand"] == 0.0
    assert any("no sales history" in w.lower() for w in data["warnings"])


def test_recommend_replenishment_with_no_sales_history_does_not_fabricate_an_order(
    no_sales_history_db,
):
    """A SKU with zero observations must not silently produce an order recommendation
    as if a real (zero) forecast had been computed - the response must carry an
    explicit warning that forecasting was not possible.
    """
    server = create_server(no_sales_history_db)

    async def go():
        return await server.call_tool("recommend_replenishment", {"sku": "DEMO-001"})

    result = asyncio.run(go())
    data = json.loads(result.content[0].text)
    assert data["forecast_model"] == "insufficient_history"
    assert data["forecast_demand"] == 0.0
    # on_hand (50) >= target_level (safety_stock only, since forecast is 0) -> no order,
    # but the warning must make clear this is "no history", not "sufficient stock".
    assert any("no sales history" in w.lower() for w in data["warnings"])


@pytest.fixture()
def two_sku_db(tmp_path):
    db_path = tmp_path / "edge.sqlite3"
    conn = connect_rw(db_path)
    init_schema(conn)
    # DEMO-001: plenty of stock and real sales history -> genuinely risk_level NONE
    # (can_assess=True), to be distinguished from DEMO-002's forced failure below.
    conn.execute("INSERT INTO products VALUES ('DEMO-001', 'Safe', 'stable', 7, 7, 0.95, 0, 1)")
    for day in range(1, 29):
        conn.execute(
            "INSERT INTO sales_history VALUES ('DEMO-001', ?, 10, 0, 0)",
            (f"2025-11-{day:02d}",),
        )
    conn.execute("INSERT INTO inventory VALUES ('DEMO-001', '2026-01-01', 500, 0, 0)")
    # DEMO-002: assessment will be made to fail via monkeypatch below.
    conn.execute("INSERT INTO products VALUES ('DEMO-002', 'Breaks', 'stable', 7, 7, 0.95, 0, 1)")
    for day in range(1, 31):
        conn.execute(
            "INSERT INTO sales_history VALUES ('DEMO-002', ?, 10, 0, 0)",
            (f"2025-12-{day:02d}",),
        )
    conn.execute("INSERT INTO inventory VALUES ('DEMO-002', '2026-01-01', 500, 0, 0)")
    conn.execute("INSERT INTO dataset_metadata VALUES (1, 1, '2026-01-01', 'test')")
    conn.commit()
    conn.close()
    return db_path


def test_detect_stockout_risk_sorts_failed_assessments_before_safe_ones(two_sku_db, monkeypatch):
    """A single SKU's assessment can fail for reasons outside the demo data (the
    `except Exception` in detect_stockout_risk is defensive, not naturally
    triggered by any validated input) - simulated here with a monkeypatch to
    confirm the failure is never sorted in among genuinely safe (risk_level
    NONE) results (post-audit finding).
    """
    import demandpilot.server as server_module

    original = server_module.inventory_logic.assess_stockout_risk

    def _boom(product, snap, forecast):
        if product.sku == "DEMO-002":
            raise RuntimeError("simulated assessment failure")
        return original(product, snap, forecast)

    monkeypatch.setattr(server_module.inventory_logic, "assess_stockout_risk", _boom)

    server = create_server(two_sku_db)

    async def go():
        return await server.call_tool("detect_stockout_risk", {"horizon_days": 14})

    result = asyncio.run(go())
    data = json.loads(result.content[0].text)
    results = data["results"]
    assert len(results) == 2

    failed = [r for r in results if r["sku"] == "DEMO-002"]
    safe = [r for r in results if r["sku"] == "DEMO-001"]
    assert len(failed) == 1 and len(safe) == 1
    assert failed[0]["can_assess"] is False
    assert failed[0]["risk_level"] == "NONE"
    assert safe[0]["can_assess"] is True
    assert safe[0]["risk_level"] == "NONE"

    # The failed assessment must come first, strictly before the genuinely safe one -
    # it must not be indistinguishable from (or sorted after) a real NONE result.
    assert results.index(failed[0]) < results.index(safe[0])
