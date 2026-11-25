"""Shared data structures passed between layers. No behavior, no I/O."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str
    product_name: str
    demand_profile: str
    lead_time_days: int
    review_period_days: int
    service_level: float
    moq: int
    pack_size: int

    @property
    def protection_period_days(self) -> int:
        return self.lead_time_days + self.review_period_days


@dataclass(frozen=True)
class SalesRecord:
    sku: str
    date: str
    quantity_sold: int
    is_promotion: bool
    is_stockout: bool


@dataclass(frozen=True)
class InventorySnapshot:
    sku: str
    as_of_date: str
    on_hand: int
    on_order: int
    reserved: int

    @property
    def inventory_position(self) -> int:
        """on_hand + eligible_on_order - reserved (MVP: all on_order is eligible)."""
        return self.on_hand + self.on_order - self.reserved


@dataclass(frozen=True)
class DatasetMetadata:
    is_synthetic: bool
    seed: int
    reference_date: str
    generator_version: str
