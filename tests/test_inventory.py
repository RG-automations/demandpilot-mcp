from __future__ import annotations

from demandpilot.logic.inventory import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_NONE,
    assess_stockout_risk,
)
from demandpilot.models import InventorySnapshot, Product


def make_product(**overrides) -> Product:
    defaults = dict(
        sku="DEMO-001",
        product_name="Test",
        demand_profile="stable",
        lead_time_days=7,
        review_period_days=7,
        service_level=0.95,
        moq=0,
        pack_size=1,
    )
    defaults.update(overrides)
    return Product(**defaults)


def make_inventory(**overrides) -> InventorySnapshot:
    defaults = dict(sku="DEMO-001", as_of_date="2026-01-01", on_hand=100, on_order=0, reserved=0)
    defaults.update(overrides)
    return InventorySnapshot(**defaults)


def test_cannot_assess_when_no_forecast():
    product = make_product()
    inventory = make_inventory()
    result = assess_stockout_risk(product, inventory, None)
    assert result.can_assess is False
    assert result.risk_level == RISK_NONE


def test_high_risk_when_no_available_stock():
    product = make_product()
    inventory = make_inventory(on_hand=5, reserved=10)
    result = assess_stockout_risk(product, inventory, [10.0] * 30)
    assert result.available_physical_stock == -5
    assert result.risk_level == RISK_HIGH
    assert result.estimated_stockout_day == 0


def test_no_risk_when_stock_covers_whole_horizon():
    product = make_product()
    inventory = make_inventory(on_hand=1000)
    result = assess_stockout_risk(product, inventory, [10.0] * 14)
    assert result.risk_level == RISK_NONE
    assert result.estimated_stockout_day is None
    assert result.can_assess is True


def test_high_risk_when_stockout_before_lead_time():
    # lead_time=7: demand of 20/day depletes 100 units on day 5 (cumulative 100 > 100? no)
    product = make_product(lead_time_days=7, review_period_days=7)
    inventory = make_inventory(on_hand=100)
    # cumulative: 30,60,90,120 -> exceeds 100 on day 4 <= lead_time(7)
    result = assess_stockout_risk(product, inventory, [30.0] * 10)
    assert result.estimated_stockout_day == 4
    assert result.risk_level == RISK_HIGH


def test_medium_risk_when_stockout_within_protection_period_after_lead_time():
    product = make_product(lead_time_days=3, review_period_days=7)  # protection = 10
    inventory = make_inventory(on_hand=50)
    # cumulative with 10/day: day5=50 -> exceeds at day 6 (>3, <=10)
    result = assess_stockout_risk(product, inventory, [10.0] * 10)
    assert result.estimated_stockout_day == 6
    assert result.risk_level == RISK_MEDIUM


def test_low_risk_when_stockout_beyond_protection_period():
    product = make_product(lead_time_days=3, review_period_days=4)  # protection = 7
    inventory = make_inventory(on_hand=100)
    # cumulative with 10/day: exceeds 100 at day 11 (> protection 7)
    result = assess_stockout_risk(product, inventory, [10.0] * 15)
    assert result.estimated_stockout_day == 11
    assert result.risk_level == RISK_LOW


def test_on_order_reported_as_context_not_used_in_risk():
    product = make_product()
    without_on_order = assess_stockout_risk(product, make_inventory(on_hand=5), [10.0] * 10)
    with_on_order = assess_stockout_risk(
        product, make_inventory(on_hand=5, on_order=500), [10.0] * 10
    )
    assert without_on_order.risk_level == with_on_order.risk_level
    assert with_on_order.on_order == 500
    assert any("on order" in w.lower() for w in with_on_order.warnings)


def test_zero_forecast_demand_means_no_risk():
    product = make_product()
    inventory = make_inventory(on_hand=5)
    result = assess_stockout_risk(product, inventory, [0.0] * 14)
    assert result.risk_level == RISK_NONE
    assert result.estimated_stockout_day is None


def test_already_negative_available_stock_is_high_risk_even_with_zero_demand():
    # reserved (10) exceeds on_hand (5): physical stock is already oversold today,
    # independent of whether any demand is forecast - this must not be reported as
    # a "day 1" future stockout (post-audit finding, see logic/inventory.py).
    product = make_product()
    inventory = make_inventory(on_hand=5, reserved=10)
    result = assess_stockout_risk(product, inventory, [0.0] * 14)
    assert result.available_physical_stock == -5
    assert result.risk_level == RISK_HIGH
    assert result.estimated_stockout_day == 0
    assert "day" not in result.justification.lower()
