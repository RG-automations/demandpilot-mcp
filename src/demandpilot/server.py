"""DemandPilot MCP server: 5 tools, 1 resource, 1 prompt, stdio transport only.

Deviation from SPECIFICATION.md section 2: the spec names
`mcp.server.fastmcp.FastMCP`, but in the locked `mcp==2.3.0` release that
class does not exist - it was renamed to `MCPServer` in the SDK's v2 line
(`from mcp.server import MCPServer`), confirmed against the official
migration guide. Behavior (the `tool()` / `resource()` / `prompt()`
decorators, stdio transport) is unchanged; only the import path differs.
This is recorded in the final report's Specification Deviations section.

All tools are read-only: the database connection is opened in read-only mode
(`sqlite3` URI `mode=ro`) and no tool ever writes to it or places an order.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from demandpilot.data import repository
from demandpilot.data.database import connect_ro
from demandpilot.forecasting import evaluation, models
from demandpilot.logic import inventory as inventory_logic
from demandpilot.logic import replenishment as replenishment_logic
from demandpilot.models import Product

SKU_PATTERN = re.compile(r"^DEMO-\d{3,}$")
MAX_SALES_HISTORY_DAYS = 730
MAX_FORECAST_HORIZON_DAYS = 90
MIN_FORECAST_HORIZON_DAYS = 1
MAX_PRODUCTS_IN_BULK_ANALYSIS = 200
PREDICTION_INTERVAL_SEED = 42

RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}


def _domain_error(code: str, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def _validate_sku_format(sku: str) -> None:
    if not SKU_PATTERN.fullmatch(sku):
        raise _domain_error(
            "INVALID_ARGUMENT", f"'{sku}' is not a valid SKU (expected format DEMO-###)."
        )


def _require_product(conn, sku: str) -> Product:
    _validate_sku_format(sku)
    product = repository.get_product(conn, sku)
    if product is None:
        raise _domain_error("SKU_NOT_FOUND", f"No product found for SKU '{sku}'.")
    return product


def _series_for_sku(conn, sku: str, reference_date: str) -> list[float]:
    rows = repository.get_sales_history(conn, sku, reference_date, MAX_SALES_HISTORY_DAYS)
    return [float(r.quantity_sold) for r in rows]


def _history_gap_info(conn, sku: str, reference_date: str) -> tuple[int, int, int]:
    """Returns (observed_days, missing_days, stockout_days)."""
    rows = repository.get_sales_history(conn, sku, reference_date, MAX_SALES_HISTORY_DAYS)
    if not rows:
        return 0, 0, 0
    first_date = date.fromisoformat(rows[0].date)
    ref = date.fromisoformat(reference_date)
    expected_days = (ref - first_date).days
    observed_days = len(rows)
    missing_days = max(0, expected_days - observed_days)
    stockout_days = sum(1 for r in rows if r.is_stockout)
    return observed_days, missing_days, stockout_days


def _daily_demand_std(series: list[float], backtest: evaluation.BacktestResult) -> float:
    if backtest.can_evaluate:
        if backtest.holt_winters is not None:
            return backtest.holt_winters["residual_std"]
        if backtest.seasonal_naive is not None:
            return backtest.seasonal_naive["residual_std"]
    return statistics.pstdev(series) if len(series) > 1 else 0.0


def create_server(db_path: Path) -> MCPServer:
    server = MCPServer(
        "demandpilot",
        version="0.1.0",
        instructions=(
            "Local, read-only demand-planning tools over a synthetic demo database. "
            "All data is fictional; this server never writes to the database or places "
            "orders."
        ),
    )

    def _conn():
        try:
            return connect_ro(db_path)
        except FileNotFoundError as exc:
            raise _domain_error("DATABASE_UNAVAILABLE", str(exc)) from exc

    @server.tool(description="Return daily sales history for one SKU.")
    def get_sales_history(
        sku: str,
        days: Annotated[int, Field(ge=1, le=MAX_SALES_HISTORY_DAYS)] = 90,
    ) -> dict:
        conn = _conn()
        try:
            product = _require_product(conn, sku)
            meta = repository.get_dataset_metadata(conn)
            rows = repository.get_sales_history(conn, product.sku, meta.reference_date, days)
            return {
                "sku": product.sku,
                "reference_date": meta.reference_date,
                "requested_days": days,
                "returned_days": len(rows),
                "records": [
                    {
                        "date": r.date,
                        "quantity_sold": r.quantity_sold,
                        "is_promotion": r.is_promotion,
                        "is_stockout": r.is_stockout,
                    }
                    for r in rows
                ],
            }
        finally:
            conn.close()

    @server.tool(description="Forecast demand for one SKU over a horizon (1-90 days).")
    def forecast_demand(
        sku: str,
        horizon_days: Annotated[
            int, Field(ge=MIN_FORECAST_HORIZON_DAYS, le=MAX_FORECAST_HORIZON_DAYS)
        ] = 14,
    ) -> dict:
        conn = _conn()
        try:
            product = _require_product(conn, sku)
            meta = repository.get_dataset_metadata(conn)
            series = _series_for_sku(conn, product.sku, meta.reference_date)
            observed_days, missing_days, stockout_days = _history_gap_info(
                conn, product.sku, meta.reference_date
            )

            try:
                point = models.generate_point_forecast(series, horizon_days)
                backtest = evaluation.run_backtest(series)
                interval = models.prediction_interval(
                    point, horizon_days, seed=PREDICTION_INTERVAL_SEED
                )
            except Exception as exc:  # defensive: forecasting must never crash the server
                raise _domain_error("FORECAST_FAILED", str(exc)) from exc

            ref = date.fromisoformat(meta.reference_date)
            daily = [
                {"date": (ref + timedelta(days=i + 1)).isoformat(), "forecast": value}
                for i, value in enumerate(point.daily_forecast)
            ]

            warnings = list(point.warnings)
            if missing_days:
                warnings.append(
                    f"{missing_days} day(s) in the history window have no recorded "
                    "observation and were excluded (not treated as zero demand)."
                )
            if stockout_days:
                warnings.append(
                    f"{stockout_days} historical day(s) were flagged as stockouts; observed "
                    "sales on those days may understate true demand."
                )
            if backtest.warning:
                warnings.append(backtest.warning)

            return {
                "sku": product.sku,
                "reference_date": meta.reference_date,
                "horizon_days": horizon_days,
                "model_used": point.model_used,
                "daily_forecast": daily,
                "total_forecast_demand": sum(point.daily_forecast),
                "prediction_interval": (
                    {
                        "lower": interval[0],
                        "upper": interval[1],
                        "coverage": 0.95,
                        "simulations": models.N_SIMULATIONS,
                    }
                    if interval is not None
                    else None
                ),
                "backtest": (
                    {
                        "test_days": backtest.test_days,
                        "holt_winters": backtest.holt_winters,
                        "seasonal_naive": backtest.seasonal_naive,
                    }
                    if backtest.can_evaluate
                    else None
                ),
                "history_length_days": observed_days,
                "warnings": warnings,
            }
        finally:
            conn.close()

    @server.tool(description="Return the current inventory snapshot for one SKU.")
    def get_inventory(sku: str) -> dict:
        conn = _conn()
        try:
            product = _require_product(conn, sku)
            snap = repository.get_inventory(conn, product.sku)
            if snap is None:
                raise _domain_error(
                    "DATABASE_UNAVAILABLE", f"No inventory snapshot for SKU '{product.sku}'."
                )
            return {
                "sku": product.sku,
                "as_of_date": snap.as_of_date,
                "on_hand": snap.on_hand,
                "on_order": snap.on_order,
                "reserved": snap.reserved,
                "inventory_position": snap.inventory_position,
                "lead_time_days": product.lead_time_days,
                "review_period_days": product.review_period_days,
                "moq": product.moq,
                "pack_size": product.pack_size,
                "service_level": product.service_level,
            }
        finally:
            conn.close()

    @server.tool(
        description="Scan all products and flag those at risk of a stockout within a horizon."
    )
    def detect_stockout_risk(
        horizon_days: Annotated[
            int, Field(ge=MIN_FORECAST_HORIZON_DAYS, le=MAX_FORECAST_HORIZON_DAYS)
        ] = 14,
    ) -> dict:
        conn = _conn()
        try:
            meta = repository.get_dataset_metadata(conn)
            products = repository.list_products(conn)[:MAX_PRODUCTS_IN_BULK_ANALYSIS]
            assessments = []
            for product in products:
                try:
                    snap = repository.get_inventory(conn, product.sku)
                    if snap is None:
                        assessments.append(
                            {
                                "sku": product.sku,
                                "can_assess": False,
                                "risk_level": "NONE",
                                "justification": "No inventory snapshot available.",
                            }
                        )
                        continue
                    series = _series_for_sku(conn, product.sku, meta.reference_date)
                    point = models.generate_point_forecast(series, horizon_days)
                    forecast = point.daily_forecast if point.daily_forecast else None
                    result = inventory_logic.assess_stockout_risk(product, snap, forecast)
                    assessments.append(asdict(result))
                except Exception as exc:  # a single bad SKU must not abort the whole scan
                    assessments.append(
                        {
                            "sku": product.sku,
                            "can_assess": False,
                            "risk_level": "NONE",
                            "justification": f"Could not be assessed: {exc}",
                        }
                    )
            assessments.sort(key=lambda a: RISK_ORDER.get(a.get("risk_level", "NONE"), 9))
            return {
                "reference_date": meta.reference_date,
                "horizon_days": horizon_days,
                "products_analyzed": len(assessments),
                "results": assessments,
            }
        finally:
            conn.close()

    @server.tool(
        description="Recommend a replenishment order quantity for one SKU (advisory only; "
        "never places an order)."
    )
    def recommend_replenishment(sku: str) -> dict:
        conn = _conn()
        try:
            product = _require_product(conn, sku)
            meta = repository.get_dataset_metadata(conn)
            snap = repository.get_inventory(conn, product.sku)
            if snap is None:
                raise _domain_error(
                    "DATABASE_UNAVAILABLE", f"No inventory snapshot for SKU '{product.sku}'."
                )

            protection_period = product.protection_period_days
            if protection_period > MAX_FORECAST_HORIZON_DAYS:
                raise _domain_error(
                    "INVALID_ARGUMENT",
                    f"Protection period ({protection_period} days) exceeds the maximum "
                    f"supported forecast horizon of {MAX_FORECAST_HORIZON_DAYS} days.",
                )

            if protection_period == 0:
                # Zero lead time and zero review period: no forecast horizon to cover,
                # so the demand term of the target level is 0 (and safety_stock is 0
                # too, since compute_safety_stock multiplies by sqrt(0)). Forecasting
                # a 0-day horizon is not just unnecessary here but actively unsafe to
                # attempt: statsmodels' Holt-Winters .forecast(0) raises ValueError.
                cumulative_forecast, daily_std, model_used, point_warnings = (
                    0.0,
                    0.0,
                    "not_applicable_zero_protection_period",
                    [],
                )
            else:
                series = _series_for_sku(conn, product.sku, meta.reference_date)
                try:
                    point = models.generate_point_forecast(series, protection_period)
                    backtest = evaluation.run_backtest(series)
                except Exception as exc:
                    raise _domain_error("FORECAST_FAILED", str(exc)) from exc
                cumulative_forecast = sum(point.daily_forecast)
                daily_std = _daily_demand_std(series, backtest)
                model_used = point.model_used
                point_warnings = list(point.warnings)

            rec = replenishment_logic.recommend_replenishment(
                product,
                snap,
                cumulative_forecast,
                daily_std,
                model_used,
                extra_warnings=point_warnings,
            )
            return {
                "sku": rec.sku,
                "inventory_position": rec.inventory_position,
                "protection_period_days": rec.protection_period_days,
                "forecast_demand": rec.forecast_demand,
                "safety_stock": rec.safety_stock,
                "target_level": rec.target_level,
                "raw_order_qty": rec.raw_order_qty,
                "final_order_qty": rec.order_qty,
                "moq": rec.moq,
                "pack_size": rec.pack_size,
                "forecast_model": rec.forecast_model,
                "justification": rec.justification,
                "warnings": rec.warnings,
            }
        finally:
            conn.close()

    @server.resource(
        "demandpilot://catalog",
        name="catalog",
        description="Read-only catalog of demo SKUs and the synthetic dataset's metadata.",
        mime_type="application/json",
    )
    def catalog() -> str:
        conn = _conn()
        try:
            meta = repository.get_dataset_metadata(conn)
            products = repository.list_products(conn)
            return json.dumps(
                {
                    "is_synthetic": True,
                    "seed": meta.seed,
                    "reference_date": meta.reference_date,
                    "generator_version": meta.generator_version,
                    "note": "All SKUs, product names, and sales figures are fictional demo data.",
                    "products": [
                        {
                            "sku": p.sku,
                            "product_name": p.product_name,
                            "demand_profile": p.demand_profile,
                        }
                        for p in products
                    ],
                },
                indent=2,
            )
        finally:
            conn.close()

    @server.prompt(
        name="weekly-replenishment-report",
        description="Guides the client through a stockout-risk review and replenishment report.",
    )
    def weekly_replenishment_report() -> str:
        return (
            "You are preparing a weekly replenishment report using only the DemandPilot MCP "
            "tools. Follow these steps in order, using tool results as your only source of "
            "numbers - never invent or recompute figures yourself:\n"
            "1. Read the `demandpilot://catalog` resource to see the available SKUs.\n"
            "2. Call `detect_stockout_risk` with horizon_days=14 to find products at risk of "
            "a stockout in the next 14 days.\n"
            "3. For each at-risk product, call `get_inventory` to review its current stock.\n"
            "4. Call `forecast_demand` for each at-risk product to review the demand outlook.\n"
            "5. Call `recommend_replenishment` for each at-risk product to get an order "
            "quantity recommendation.\n"
            "6. Explain the reasoning behind each recommendation using the tool's own "
            "`justification` field.\n"
            "7. Clearly state the forecasting model used and any warnings or limitations "
            "returned by the tools.\n"
            "8. Present a decision-support report for human review. This is advisory only: "
            "no order is placed, and nothing here should be presented as an automated or "
            "already-approved purchase."
        )

    return server


def run(db_path: Path) -> None:
    server = create_server(db_path)
    server.run(transport="stdio")


if __name__ == "__main__":
    print("Run via `python -m demandpilot --db <path>` instead.", file=sys.stderr)
    sys.exit(1)
