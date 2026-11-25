from __future__ import annotations

import pytest

from demandpilot.logic.replenishment import (
    compute_order_qty,
    compute_raw_order_qty,
    compute_safety_stock,
    compute_target_level,
    recommend_replenishment,
    z_score_for_service_level,
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
        moq=50,
        pack_size=12,
    )
    defaults.update(overrides)
    return Product(**defaults)


def make_inventory(**overrides) -> InventorySnapshot:
    defaults = dict(sku="DEMO-001", as_of_date="2026-01-01", on_hand=150, on_order=0, reserved=0)
    defaults.update(overrides)
    return InventorySnapshot(**defaults)


def test_z_score_matches_normal_dist_inv_cdf():
    assert z_score_for_service_level(0.95) == pytest.approx(1.6448536269514715)


def test_z_score_rejects_out_of_range_service_level():
    with pytest.raises(ValueError):
        z_score_for_service_level(1.0)
    with pytest.raises(ValueError):
        z_score_for_service_level(0.0)


def test_safety_stock_rejects_negative_protection_period():
    with pytest.raises(ValueError):
        compute_safety_stock(1.65, 10, -1)


def test_safety_stock_hand_calculated():
    # z(0.95) * 10 * sqrt(14) == 61.544787234448826 (verified independently)
    ss = compute_safety_stock(
        z_score=1.6448536269514715, daily_demand_std=10, protection_period_days=14
    )
    assert ss == pytest.approx(61.544787234448826)


def test_safety_stock_zero_when_std_zero():
    assert compute_safety_stock(1.65, 0.0, 14) == 0.0


def test_safety_stock_floored_at_zero_for_service_level_below_half():
    """z_score_for_service_level(service_level < 0.5) is negative; safety stock must not
    go negative as a result (post-audit finding L1 - documented policy, not a bug).
    """
    negative_z = z_score_for_service_level(0.3)
    assert negative_z < 0
    assert compute_safety_stock(negative_z, 10, 14) == 0.0


def test_safety_stock_zero_at_service_level_one_half():
    assert z_score_for_service_level(0.5) == pytest.approx(0.0, abs=1e-12)
    assert compute_safety_stock(z_score_for_service_level(0.5), 10, 14) == pytest.approx(0.0)


def test_target_level_is_forecast_plus_safety_stock():
    assert compute_target_level(200, 61.5) == pytest.approx(261.5)


def test_raw_order_qty_zero_when_inventory_covers_target():
    assert compute_raw_order_qty(target_level=200, inventory_position=250) == 0.0


def test_raw_order_qty_positive_difference():
    assert compute_raw_order_qty(target_level=261.5, inventory_position=150) == pytest.approx(111.5)


def test_raw_order_qty_handles_negative_inventory_position():
    assert compute_raw_order_qty(target_level=100, inventory_position=-20) == pytest.approx(120)


@pytest.mark.parametrize(
    "raw_qty, moq, pack_size, expected",
    [
        (0, 50, 12, 0),  # no order needed
        (111.544787234448826, 50, 12, 120),  # hand-calculated end-to-end example
        (5, 50, 12, 60),  # MOQ larger than raw recommendation, MOQ not a multiple of pack size
        (10, 0, 5, 10),  # zero MOQ, rounds up to pack size multiple
        (13, 0, 5, 15),
    ],
)
def test_compute_order_qty_cases(raw_qty, moq, pack_size, expected):
    assert compute_order_qty(raw_qty, moq, pack_size) == expected


def test_compute_order_qty_rejects_invalid_pack_size():
    with pytest.raises(ValueError):
        compute_order_qty(10, 0, 0)


def test_compute_order_qty_rejects_negative_moq():
    with pytest.raises(ValueError):
        compute_order_qty(10, -1, 5)


def test_compute_order_qty_exact_multiple_boundary_not_affected_by_epsilon():
    # Exactly 10 packs of 12: must stay 120, not round up to 11 packs.
    assert compute_order_qty(120.0, moq=0, pack_size=12) == 120


def test_compute_order_qty_float_noise_just_above_exact_multiple_does_not_overround():
    """Post-audit finding L2: floating-point noise landing a hair above an exact
    multiple of pack_size must not add a whole extra pack.
    """
    assert compute_order_qty(120.0 + 1e-9, moq=0, pack_size=12) == 120


def test_compute_order_qty_genuine_fraction_just_below_a_multiple_still_rounds_up():
    # A real (non-float-noise) need of 119.9 units still needs 10 packs of 12, not 9.
    assert compute_order_qty(119.9, moq=0, pack_size=12) == 120


def test_recommend_replenishment_end_to_end_hand_calculated():
    product = make_product(
        lead_time_days=7, review_period_days=7, service_level=0.95, moq=50, pack_size=12
    )
    inventory = make_inventory(on_hand=150, on_order=0, reserved=0)
    rec = recommend_replenishment(
        product,
        inventory,
        cumulative_forecast_demand=200,
        daily_demand_std=10,
        forecast_model="holt_winters",
    )
    assert rec.protection_period_days == 14
    assert rec.safety_stock == pytest.approx(61.544787234448826)
    assert rec.target_level == pytest.approx(261.544787234448826)
    assert rec.inventory_position == 150
    assert rec.raw_order_qty == pytest.approx(111.544787234448826)
    assert rec.order_qty == 120
    assert rec.warnings == []


def test_recommend_replenishment_no_order_needed_when_overstocked():
    product = make_product()
    inventory = make_inventory(on_hand=1000)
    rec = recommend_replenishment(
        product,
        inventory,
        cumulative_forecast_demand=50,
        daily_demand_std=5,
        forecast_model="seasonal_naive",
    )
    assert rec.raw_order_qty == 0
    assert rec.order_qty == 0
    assert "no order" in rec.justification.lower()


def test_recommend_replenishment_flags_negative_inventory_position():
    product = make_product()
    inventory = make_inventory(on_hand=10, on_order=0, reserved=50)
    rec = recommend_replenishment(
        product,
        inventory,
        cumulative_forecast_demand=100,
        daily_demand_std=5,
        forecast_model="naive",
    )
    assert rec.inventory_position == -40
    assert any("negative" in w.lower() for w in rec.warnings)
    assert rec.order_qty > 0


def test_recommend_replenishment_zero_forecast_demand_still_applies_safety_stock():
    product = make_product(moq=0, pack_size=1)
    inventory = make_inventory(on_hand=0)
    rec = recommend_replenishment(
        product,
        inventory,
        cumulative_forecast_demand=0,
        daily_demand_std=0,
        forecast_model="zero_demand",
    )
    assert rec.target_level == 0
    assert rec.order_qty == 0


def test_recommend_replenishment_carries_on_order_into_inventory_position():
    product = make_product()
    inventory = make_inventory(on_hand=50, on_order=100, reserved=0)
    rec = recommend_replenishment(
        product,
        inventory,
        cumulative_forecast_demand=100,
        daily_demand_std=5,
        forecast_model="holt_winters",
    )
    assert rec.inventory_position == 150
