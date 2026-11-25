# Demo Scenario

> **What this document is**: a walk-through of the DemandPilot MCP tools using real responses
> captured by calling the running server (see `examples/sample_responses/*.json`, generated from
> the seed-42 demo database, reference date 2026-01-01). **The narrative interpretation in step 6
> was written by hand from those real tool outputs; it illustrates how an AI client *would*
> narrate them, but was not produced by an actual live AI-client session against this server.**
> Running it with a real client (Claude Desktop/Code) is left to the person deploying it - see
> `examples/claude_desktop_config.json` / `examples/claude_code_config.json`.

## Scenario prompt

> Analyze the next 14 days of demand and identify products at risk of stockouts. Review their
> inventory positions, recommend replenishment quantities, explain the calculations, and
> highlight any forecasting limitations.

This matches the `weekly-replenishment-report` MCP prompt's intended workflow.

## Step 1: Read the catalog resource

Request: read resource `demandpilot://catalog`.

Real response (`examples/sample_responses/catalog_resource.json`, truncated):

```json
{
  "is_synthetic": true,
  "seed": 42,
  "reference_date": "2026-01-01",
  "generator_version": "1.0.0",
  "note": "All SKUs, product names, and sales figures are fictional demo data.",
  "products": [
    { "sku": "DEMO-001", "product_name": "Demo Product 01 (Stable)", "demand_profile": "stable" },
    { "sku": "DEMO-002", "product_name": "Demo Product 02 (Weekly Seasonality)", "demand_profile": "weekly_seasonality" },
    { "sku": "DEMO-003", "product_name": "Demo Product 03 (Trend Up)", "demand_profile": "trend_up" }
    // ... 17 more SKUs
  ]
}
```

## Step 2: `detect_stockout_risk(horizon_days=14)`

Real response summary (full payload in `examples/sample_responses/detect_stockout_risk.json`):
20 products analyzed, 10 `HIGH`, 2 `MEDIUM`, 8 `NONE`, 0 `LOW` in this particular seed/horizon
(no SKU came back `can_assess: false` here, because even the short-history SKU has enough
history for the Seasonal Naive fallback).

```json
{
  "sku": "DEMO-003",
  "on_hand": 175,
  "reserved": 0,
  "on_order": 292,
  "available_physical_stock": 175,
  "forecast_horizon_demand": 429.52,
  "estimated_stockout_day": 6,
  "risk_level": "HIGH",
  "justification": "Projected to run out on day 6, before the 21-day lead time elapses; a reorder placed today could not arrive in time.",
  "warnings": [
    "292 units are on order; not counted toward available stock because exact arrival dates are unknown (conservative assumption)."
  ]
}
```

`DEMO-003` is a good illustration of why stockout-risk assessment deliberately ignores
`on_order` (SPECIFICATION.md section 6.6): 292 units are already incoming, but without a known
arrival date the conservative assumption is that they cannot be counted as available physical
stock, so the SKU is still flagged `HIGH`. Compare this with `inventory_position` in the next
step, which *does* count the incoming order.

## Step 3: `get_inventory(sku="DEMO-003")`

```json
{
  "sku": "DEMO-003",
  "as_of_date": "2026-01-01",
  "on_hand": 175,
  "on_order": 292,
  "reserved": 0,
  "inventory_position": 467,
  "lead_time_days": 21,
  "review_period_days": 9,
  "moq": 50,
  "pack_size": 12,
  "service_level": 0.95
}
```

## Step 4: `forecast_demand(sku="DEMO-003", horizon_days=14)`

See `examples/sample_responses/get_sales_history.json` for the raw history behind this, and
`examples/sample_responses/forecast_demand.json` for a full response on DEMO-002, which shows a
case where the Seasonal Naive baseline actually scores better than Holt-Winters on the backtest
(WAPE 14.83% vs 17.80%) - reported honestly rather than hidden (see `docs/METHODOLOGY.md`
"When the baseline wins").

Other real examples captured for this demo:
- `examples/sample_responses/forecast_demand_fallback_short_history.json` - `DEMO-009` (20 days
  of history) falls back to `seasonal_naive` with an explicit warning that the backtest could not
  run.
- `examples/sample_responses/forecast_demand_zero_demand.json` - `DEMO-008` (a "no sales" SKU)
  returns `model_used: "zero_demand"` with an explicit warning, not a fabricated nonzero forecast.

## Step 5: `recommend_replenishment(sku="DEMO-003")`

```json
{
  "sku": "DEMO-003",
  "inventory_position": 467,
  "protection_period_days": 30,
  "forecast_demand": 920.6028548852669,
  "safety_stock": 42.076858574574146,
  "target_level": 962.679713459841,
  "raw_order_qty": 495.67971345984097,
  "final_order_qty": 504,
  "moq": 50,
  "pack_size": 12,
  "forecast_model": "holt_winters",
  "justification": "Target stock level (962.7) exceeds inventory position (467) by 495.7 over the 30-day protection period; rounded up to MOQ 50 and pack size 12 gives an order quantity of 504.",
  "warnings": []
}
```

Note the 292 units on order *do* reduce the recommended order quantity here (504 units, not the
~820 units it would be without them) - `recommend_replenishment` correctly counts them as part of
`inventory_position` (section 6.1), while `detect_stockout_risk` in Step 2 just as correctly
ignored them for the conservative risk assessment. This is not an inconsistency: it is the two
tools answering two different questions ("how much should I order, given everything already
committed" vs. "could I physically run out before anything arrives").

For contrast, `examples/sample_responses/recommend_replenishment_no_order_needed.json`
(`DEMO-002`) shows the zero-order case: inventory position 837 already exceeds the 558.3 target
level, so `final_order_qty: 0`.

## Step 6: Illustrative report (hand-written from the outputs above, not an executed AI session)

> **Weekly Replenishment Report - 2026-01-01**
>
> Of 20 demo SKUs, 10 are at **HIGH** risk of a stockout within 14 days and 2 are at **MEDIUM**
> risk. `DEMO-003` is a clear case: with 175 units on hand, its Holt-Winters forecast of ~430
> units of demand over the next 14 days would exhaust physical stock by day 6 - well before its
> 21-day lead time, so a replenishment order placed today would still arrive late for this cycle.
> 292 units are already on order, but with no known arrival date they are conservatively excluded
> from this risk check. Based on its 30-day protection period (21-day lead time + 9-day review
> period) and counting the incoming order toward inventory position, the recommended order is
> **504 units** (target level 962.7 minus inventory position 467, rounded up to its MOQ of 50 and
> pack size of 12).
>
> **Limitations**: this forecast used Holt-Winters with an additive weekly seasonal component;
> prediction intervals and backtest accuracy are available in the full tool response. Safety
> stock assumes independent, normally distributed daily demand and a fixed lead time - it is not
> a guaranteed service level. This report is **advisory only**: no order has been placed, and it
> requires human review before action.

## Running this yourself

```bash
python -m demandpilot.data_gen --seed 42 --reference-date 2026-01-01 --db ./demo.sqlite3
python -m demandpilot --db ./demo.sqlite3
```

Then point Claude Desktop or Claude Code at it using
`examples/claude_desktop_config.json` / `examples/claude_code_config.json` (replace the
placeholder paths with your actual project path) and ask the scenario prompt above.
