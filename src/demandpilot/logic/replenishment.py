"""Periodic-review (R, S) replenishment logic. Pure functions, no I/O, no MCP.

Assumptions (documented per SPECIFICATION.md section 6.3):
- Lead time is treated as fixed/deterministic (no supply uncertainty).
- Daily demand deviations are assumed independent and approximately normal.
- `service_level` is an approximate cycle service level, not a guaranteed
  customer service level.
- The whole `on_order` quantity is treated as eligible within the protection
  period (no delivery-date scheduling in this MVP).
- Safety stock is floored at 0 (never negative): a `service_level` below 0.5
  gives a negative z-score, but a safety buffer that *reduces* the target
  level below the plain cumulative forecast is not a meaningful "buffer" in
  this model - it would mean deliberately planning to stock less than the
  forecast itself. The schema only enforces `0 < service_level < 1`, so a
  caller is free to pick a value below 0.5; this floor is what happens if
  they do, documented here rather than left as a silent implementation
  detail (post-audit finding L1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

from demandpilot.models import InventorySnapshot, Product


def z_score_for_service_level(service_level: float) -> float:
    if not 0 < service_level < 1:
        raise ValueError(f"service_level must be in (0, 1), got {service_level}")
    return NormalDist().inv_cdf(service_level)


def compute_safety_stock(
    z_score: float, daily_demand_std: float, protection_period_days: int
) -> float:
    """Floors the result at 0: a service_level below 0.5 gives a negative z-score, but
    safety stock is a buffer on top of the forecast, not a deliberate reduction below
    it - see the module assumptions above.
    """
    if protection_period_days < 0:
        raise ValueError("protection_period_days must be >= 0")
    return max(0.0, z_score) * max(0.0, daily_demand_std) * math.sqrt(protection_period_days)


def compute_target_level(cumulative_forecast: float, safety_stock: float) -> float:
    return cumulative_forecast + safety_stock


def compute_raw_order_qty(target_level: float, inventory_position: float) -> float:
    return max(0.0, target_level - inventory_position)


def compute_order_qty(raw_order_qty: float, moq: int, pack_size: int) -> int:
    """ceil(max(raw_order_qty, moq) / pack_size) * pack_size, or 0 if nothing is needed.

    Subtracts a tiny epsilon before `ceil` (post-audit finding L2): without it, floating-
    point noise that lands a hair above an exact multiple of `pack_size` (e.g. base ==
    120.0 + 1e-9) rounds up to one extra whole pack. The epsilon is many orders of
    magnitude smaller than a single unit, so it can only correct this noise - it cannot
    cause under-ordering for any genuine fractional need.
    """
    if pack_size <= 0:
        raise ValueError(f"pack_size must be > 0, got {pack_size}")
    if moq < 0:
        raise ValueError(f"moq must be >= 0, got {moq}")
    if raw_order_qty <= 0:
        return 0
    base = max(raw_order_qty, moq)
    return math.ceil(base / pack_size - 1e-9) * pack_size


@dataclass(frozen=True)
class ReplenishmentRecommendation:
    sku: str
    inventory_position: float
    protection_period_days: int
    forecast_demand: float
    safety_stock: float
    target_level: float
    raw_order_qty: float
    order_qty: int
    moq: int
    pack_size: int
    forecast_model: str
    justification: str
    warnings: list[str] = field(default_factory=list)


def recommend_replenishment(
    product: Product,
    inventory: InventorySnapshot,
    cumulative_forecast_demand: float,
    daily_demand_std: float,
    forecast_model: str,
    extra_warnings: list[str] | None = None,
) -> ReplenishmentRecommendation:
    protection_period = product.protection_period_days
    z = z_score_for_service_level(product.service_level)
    safety_stock = compute_safety_stock(z, daily_demand_std, protection_period)
    target_level = compute_target_level(cumulative_forecast_demand, safety_stock)
    inv_position = inventory.inventory_position
    raw_qty = compute_raw_order_qty(target_level, inv_position)
    order_qty = compute_order_qty(raw_qty, product.moq, product.pack_size)

    warnings: list[str] = list(extra_warnings or [])
    if inv_position < 0:
        warnings.append("Inventory position is negative (reservations exceed on-hand + on-order).")
    if order_qty == 0 and raw_qty == 0:
        justification = (
            f"Inventory position ({inv_position:g}) already covers the target stock level "
            f"({target_level:.1f}) for the {protection_period}-day protection period; no order "
            "is recommended."
        )
    else:
        justification = (
            f"Target stock level ({target_level:.1f}) exceeds inventory position "
            f"({inv_position:g}) by {raw_qty:.1f} over the {protection_period}-day protection "
            f"period; rounded up to MOQ {product.moq} and pack size {product.pack_size} gives "
            f"an order quantity of {order_qty}."
        )

    return ReplenishmentRecommendation(
        sku=product.sku,
        inventory_position=inv_position,
        protection_period_days=protection_period,
        forecast_demand=cumulative_forecast_demand,
        safety_stock=safety_stock,
        target_level=target_level,
        raw_order_qty=raw_qty,
        order_qty=order_qty,
        moq=product.moq,
        pack_size=product.pack_size,
        forecast_model=forecast_model,
        justification=justification,
        warnings=warnings,
    )
