"""Inventory-position and stockout-risk analysis. Pure functions, no I/O, no MCP.

Risk is a rule-based classification over the available physical stock
(on_hand - reserved), deliberately not a statistical probability, per
SPECIFICATION.md section 6.6:
  - HIGH:   stock already exhausted today, or projected to run out before
            lead time elapses (a reorder today could not arrive in time).
  - MEDIUM: projected to run out after lead time but still within the full
            protection period (lead time + review period).
  - LOW:    projected to run out, but only beyond the protection period.
  - NONE:   not projected to run out within the forecast horizon.
`on_order` is reported as context only; it is not used to compute risk,
because without delivery-date scheduling it is not conservative to assume it
arrives before the stockout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from demandpilot.models import InventorySnapshot, Product

RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_NONE = "NONE"


@dataclass(frozen=True)
class StockoutRiskAssessment:
    sku: str
    on_hand: int
    reserved: int
    on_order: int
    available_physical_stock: int
    forecast_horizon_demand: float | None
    estimated_stockout_day: int | None
    risk_level: str
    can_assess: bool
    justification: str
    warnings: list[str] = field(default_factory=list)


def assess_stockout_risk(
    product: Product,
    inventory: InventorySnapshot,
    daily_forecast: list[float] | None,
) -> StockoutRiskAssessment:
    """`daily_forecast` is the day-by-day forecast for the full analysis horizon,
    starting at day 1 (tomorrow). None/empty means forecasting could not be
    performed for this SKU.
    """
    available = inventory.on_hand - inventory.reserved
    warnings: list[str] = []
    if inventory.on_order > 0:
        warnings.append(
            f"{inventory.on_order} units are on order; not counted toward available stock "
            "because exact arrival dates are unknown (conservative assumption)."
        )

    if daily_forecast is None or len(daily_forecast) == 0:
        return StockoutRiskAssessment(
            sku=product.sku,
            on_hand=inventory.on_hand,
            reserved=inventory.reserved,
            on_order=inventory.on_order,
            available_physical_stock=available,
            forecast_horizon_demand=None,
            estimated_stockout_day=None,
            risk_level=RISK_NONE,
            can_assess=False,
            justification="Insufficient sales history to forecast demand for this SKU.",
            warnings=warnings,
        )

    horizon_demand = sum(daily_forecast)

    if available <= 0 and horizon_demand > 0:
        return StockoutRiskAssessment(
            sku=product.sku,
            on_hand=inventory.on_hand,
            reserved=inventory.reserved,
            on_order=inventory.on_order,
            available_physical_stock=available,
            forecast_horizon_demand=horizon_demand,
            estimated_stockout_day=0,
            risk_level=RISK_HIGH,
            can_assess=True,
            justification="No available physical stock after reservations.",
            warnings=warnings,
        )

    cumulative = 0.0
    stockout_day: int | None = None
    for day_index, demand in enumerate(daily_forecast, start=1):
        cumulative += demand
        if cumulative > available:
            stockout_day = day_index
            break

    protection_period = product.protection_period_days
    if stockout_day is None:
        risk = RISK_NONE
        justification = (
            f"Forecasted demand ({horizon_demand:.1f}) over the {len(daily_forecast)}-day "
            f"horizon does not exceed available stock ({available})."
        )
    elif stockout_day <= product.lead_time_days:
        risk = RISK_HIGH
        justification = (
            f"Projected to run out on day {stockout_day}, before the {product.lead_time_days}"
            "-day lead time elapses; a reorder placed today could not arrive in time."
        )
    elif stockout_day <= protection_period:
        risk = RISK_MEDIUM
        justification = (
            f"Projected to run out on day {stockout_day}, within the {protection_period}-day "
            "protection period but after lead time has elapsed."
        )
    else:
        risk = RISK_LOW
        justification = (
            f"Projected to run out on day {stockout_day}, beyond the {protection_period}-day "
            "protection period."
        )

    return StockoutRiskAssessment(
        sku=product.sku,
        on_hand=inventory.on_hand,
        reserved=inventory.reserved,
        on_order=inventory.on_order,
        available_physical_stock=available,
        forecast_horizon_demand=horizon_demand,
        estimated_stockout_day=stockout_day,
        risk_level=risk,
        can_assess=True,
        justification=justification,
        warnings=warnings,
    )
