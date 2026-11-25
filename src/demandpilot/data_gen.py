"""Deterministic synthetic demo-data generator for DemandPilot MCP.

All data produced here is fictional. It is used only to populate a local demo
database; it is never used as a hidden input to the forecasting layer, which
reads nothing but the `sales_history` table.

CLI:
    python -m demandpilot.data_gen \\
        --seed 42 --reference-date 2026-01-01 --sku-count 20 \\
        --history-days 730 --db ./demo.sqlite3 [--overwrite]
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from demandpilot.data.database import connect_rw, init_schema

GENERATOR_VERSION = "1.0.0"

DEMAND_PROFILES = [
    "stable",
    "weekly_seasonality",
    "trend_up",
    "trend_down",
    "promotional",
    "intermittent",
    "slow_mover",
    "no_sales",
    "short_history",
    "historical_stockout",
]

INVENTORY_SCENARIOS = [
    "at_risk_stockout",
    "overstocked",
    "needs_order",
    "no_order_needed",
    # on_order/reserved were previously always 0 for every SKU in the demo dataset
    # (post-audit finding M4): these three scenarios exercise the real difference
    # between physical stock, Inventory Position, and stockout-risk assessment -
    # see SPECIFICATION.md sections 6.1 and 6.6, and docs/METHODOLOGY.md.
    "needs_order_with_incoming",
    "at_risk_with_reservations",
    "mixed_on_order_and_reserved",
]

# Fraction of otherwise-valid days with no sales_history row at all, to model
# missing observations distinct from genuine zero demand (spec section 5.4).
MISSING_OBSERVATION_RATE = 0.02
SHORT_HISTORY_DAYS = 20

# Lead time / review period bounds are kept well under the 90-day forecast
# horizon limit (max protection period 21 + 14 = 35 days) so that every
# generated SKU stays inside the MCP tool validation range (spec 8.4).
LEAD_TIME_RANGE = (3, 21)
REVIEW_PERIOD_RANGE = (7, 14)
SERVICE_LEVELS = (0.90, 0.95, 0.97, 0.98)
PACK_SIZES = (1, 5, 10, 12, 24)
MOQS = (0, 20, 50, 100)


@dataclass
class SkuPlan:
    index: int
    sku: str
    demand_profile: str
    inventory_scenario: str


def build_sku_plans(sku_count: int) -> list[SkuPlan]:
    plans = []
    for i in range(1, sku_count + 1):
        profile = DEMAND_PROFILES[(i - 1) % len(DEMAND_PROFILES)]
        scenario = INVENTORY_SCENARIOS[(i - 1 + 2) % len(INVENTORY_SCENARIOS)]
        plans.append(SkuPlan(i, f"DEMO-{i:03d}", profile, scenario))
    return plans


def _clip_nonneg_int(value: float) -> int:
    return max(0, round(value))


def _generate_daily_quantity(
    profile: str,
    day_index: int,
    total_days: int,
    weekday: int,
    baseline: float,
    rng: random.Random,
) -> tuple[int, bool, bool]:
    """Returns (quantity, is_promotion, is_stockout) for one observed day."""
    if profile == "no_sales":
        return 0, False, False

    if profile == "weekly_seasonality":
        weekday_multiplier = [1.4, 1.0, 0.9, 0.9, 1.0, 1.3, 1.6][weekday]
        mean = baseline * weekday_multiplier
        return _clip_nonneg_int(rng.gauss(mean, mean * 0.15)), False, False

    if profile == "trend_up":
        progress = day_index / max(total_days - 1, 1)
        mean = baseline * (0.5 + 1.3 * progress)
        return _clip_nonneg_int(rng.gauss(mean, mean * 0.15)), False, False

    if profile == "trend_down":
        progress = day_index / max(total_days - 1, 1)
        mean = baseline * (1.6 - 1.1 * progress)
        return _clip_nonneg_int(rng.gauss(mean, mean * 0.15)), False, False

    if profile == "promotional":
        in_promo = (day_index % 25) < 4
        mean = baseline * (3.2 if in_promo else 1.0)
        qty = _clip_nonneg_int(rng.gauss(mean, mean * 0.15))
        return qty, in_promo, False

    if profile == "intermittent":
        if rng.random() < 0.25:
            return rng.randint(1, 6), False, False
        return 0, False, False

    if profile == "slow_mover":
        if rng.random() < 0.3:
            return rng.choice([1, 1, 2]), False, False
        return 0, False, False

    if profile == "historical_stockout":
        in_stockout_window = (day_index % 180) >= 90 and (day_index % 180) < 95
        mean = baseline
        qty = _clip_nonneg_int(rng.gauss(mean, mean * 0.15))
        if in_stockout_window:
            capped = min(qty, max(1, round(baseline * 0.2)))
            return capped, False, True
        return qty, False, False

    # "stable" and "short_history" (short_history uses the stable generator,
    # the shortening happens by truncating the date range, not the formula).
    return _clip_nonneg_int(rng.gauss(baseline, baseline * 0.15)), False, False


def _generate_sales_rows(
    plan: SkuPlan, baseline: float, reference_date: date, history_days: int, rng: random.Random
) -> list[tuple[str, str, int, int, int]]:
    if plan.demand_profile == "short_history":
        active_days = min(SHORT_HISTORY_DAYS, history_days)
    else:
        active_days = history_days

    start_date = reference_date - timedelta(days=active_days)
    rows = []
    for day_index in range(active_days):
        current = start_date + timedelta(days=day_index)
        if plan.demand_profile not in ("no_sales", "short_history"):
            if rng.random() < MISSING_OBSERVATION_RATE:
                continue  # missing observation: no row, not a zero-demand row
        quantity, is_promo, is_stockout = _generate_daily_quantity(
            plan.demand_profile, day_index, active_days, current.weekday(), baseline, rng
        )
        rows.append((plan.sku, current.isoformat(), quantity, int(is_promo), int(is_stockout)))
    return rows


def _generate_inventory_row(
    plan: SkuPlan, avg_daily_demand: float, protection_period: int, reference_date: date
) -> tuple[str, str, int, int, int]:
    expected = avg_daily_demand * protection_period
    if plan.inventory_scenario == "at_risk_stockout":
        on_hand = _clip_nonneg_int(expected * 0.25) if expected > 0 else 0
        on_order, reserved = 0, 0
    elif plan.inventory_scenario == "overstocked":
        on_hand = _clip_nonneg_int(expected * 4 + 50) if expected > 0 else 50
        on_order, reserved = 0, 0
    elif plan.inventory_scenario == "needs_order":
        on_hand = _clip_nonneg_int(expected * 0.6) if expected > 0 else 5
        on_order, reserved = 0, 0
    elif plan.inventory_scenario == "no_order_needed":
        on_hand = _clip_nonneg_int(expected * 1.6 + 20) if expected > 0 else 20
        on_order, reserved = 0, 0
    elif plan.inventory_scenario == "needs_order_with_incoming":
        # Physical stock alone is as low as "needs_order", but a shipment already on
        # order covers most of the gap: Inventory Position (on_hand + on_order) is
        # much higher than physical stock, so the recommended order quantity should
        # be smaller than a SKU with identical on_hand and no incoming order - while
        # stockout risk, which conservatively ignores on_order (section 6.6), is still
        # assessed from physical stock alone.
        on_hand = _clip_nonneg_int(expected * 0.3) if expected > 0 else 5
        on_order = _clip_nonneg_int(expected * 0.5) if expected > 0 else 10
        reserved = 0
    elif plan.inventory_scenario == "at_risk_with_reservations":
        # on_hand looks adequate on its own, but a chunk of it is already reserved
        # against existing commitments (section 6.1): both Inventory Position and the
        # stockout-risk "available" figure must come out lower than on_hand alone.
        on_hand = _clip_nonneg_int(expected * 0.9) if expected > 0 else 15
        on_order = 0
        reserved = _clip_nonneg_int(expected * 0.5) if expected > 0 else 8
    else:  # mixed_on_order_and_reserved
        # Both terms of Inventory Position are non-zero at once, and they pull in
        # opposite directions: a reservation reduces both Inventory Position and
        # physical available stock equally, while an incoming order raises Inventory
        # Position (and the replenishment recommendation) without raising the
        # physical stock that stockout-risk assessment relies on.
        on_hand = _clip_nonneg_int(expected * 0.5) if expected > 0 else 10
        on_order = _clip_nonneg_int(expected * 0.4) if expected > 0 else 6
        reserved = _clip_nonneg_int(expected * 0.2) if expected > 0 else 3
    return (plan.sku, reference_date.isoformat(), on_hand, on_order, reserved)


def generate(
    seed: int, reference_date: date, sku_count: int, history_days: int
) -> tuple[list[tuple], list[tuple], list[tuple], tuple]:
    """Builds (products_rows, sales_rows, inventory_rows, metadata_row) deterministically."""
    rng = random.Random(seed)
    plans = build_sku_plans(sku_count)

    products_rows = []
    sales_rows: list[tuple] = []
    inventory_rows = []

    for plan in plans:
        lead_time = rng.randint(*LEAD_TIME_RANGE)
        review_period = rng.randint(*REVIEW_PERIOD_RANGE)
        service_level = rng.choice(SERVICE_LEVELS)
        pack_size = rng.choice(PACK_SIZES)
        moq = rng.choice(MOQS)
        baseline = 5 + (plan.index % 7) * 4
        if plan.demand_profile == "slow_mover":
            baseline = 1.0
        elif plan.demand_profile == "no_sales":
            baseline = 0.0

        product_label = plan.demand_profile.replace("_", " ").title()
        products_rows.append(
            (
                plan.sku,
                f"Demo Product {plan.index:02d} ({product_label})",
                plan.demand_profile,
                lead_time,
                review_period,
                service_level,
                moq,
                pack_size,
            )
        )

        rows = _generate_sales_rows(plan, baseline, reference_date, history_days, rng)
        sales_rows.extend(rows)

        observed_quantities = [r[2] for r in rows]
        avg_daily_demand = (
            sum(observed_quantities) / len(observed_quantities) if observed_quantities else 0.0
        )
        protection_period = lead_time + review_period
        inventory_rows.append(
            _generate_inventory_row(plan, avg_daily_demand, protection_period, reference_date)
        )

    metadata_row = (1, seed, reference_date.isoformat(), GENERATOR_VERSION)
    return products_rows, sales_rows, inventory_rows, metadata_row


def write_database(
    db_path: Path, seed: int, reference_date: date, sku_count: int, history_days: int
) -> None:
    products_rows, sales_rows, inventory_rows, metadata_row = generate(
        seed, reference_date, sku_count, history_days
    )
    conn = connect_rw(db_path)
    try:
        init_schema(conn)
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)", products_rows)
        conn.executemany("INSERT INTO sales_history VALUES (?, ?, ?, ?, ?)", sales_rows)
        conn.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?)", inventory_rows)
        conn.execute("INSERT INTO dataset_metadata VALUES (?, ?, ?, ?)", metadata_row)
        conn.commit()
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-date", type=str, default="2026-01-01")
    parser.add_argument("--sku-count", type=int, default=20)
    parser.add_argument("--history-days", type=int, default=730)
    parser.add_argument("--db", type=str, default="./demo.sqlite3")
    parser.add_argument(
        "--overwrite", action="store_true", help="Allow overwriting an existing database file."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        reference_date = date.fromisoformat(args.reference_date)
    except ValueError:
        print(
            f"Invalid --reference-date: {args.reference_date!r} (expected YYYY-MM-DD)",
            file=sys.stderr,
        )
        return 1
    if args.sku_count < 1:
        print("--sku-count must be >= 1", file=sys.stderr)
        return 1
    if args.history_days < 1 or args.history_days > 730:
        print("--history-days must be between 1 and 730", file=sys.stderr)
        return 1

    db_path = Path(args.db)
    if db_path.exists() and not args.overwrite:
        print(
            f"Database already exists at {db_path}. Pass --overwrite to replace it.",
            file=sys.stderr,
        )
        return 1
    if db_path.exists() and args.overwrite:
        db_path.unlink()

    write_database(db_path, args.seed, reference_date, args.sku_count, args.history_days)
    print(
        f"Generated demo database at {db_path} (seed={args.seed}, "
        f"reference_date={reference_date.isoformat()}, sku_count={args.sku_count})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
