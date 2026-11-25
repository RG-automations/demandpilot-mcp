# Methodology

This document explains the forecasting and inventory methods behind DemandPilot MCP in plain
Supply Chain language, with one fully worked, hand-checked example. Every formula here matches
the implementation exactly (`src/demandpilot/logic/replenishment.py`,
`src/demandpilot/logic/inventory.py`, `src/demandpilot/forecasting/`) and the numbers below are
asserted in `tests/test_replenishment.py::test_recommend_replenishment_end_to_end_hand_calculated`.

## 1. Forecasting

### Holt-Winters

Holt-Winters (triple exponential smoothing) is the primary model. It is fit with an additive
weekly seasonal component (`seasonal_periods=7`) and no trend component, which is the simplest
variant that still captures day-of-week seasonality in daily sales data. It is used only when at
least 21 days of history (three full weekly cycles) are available and the fit produces finite,
usable values; fewer than three cycles risks overfitting a model with 7+ free seasonal
parameters to very little data.

### Seasonal Naive

The reference (baseline) model. It simply repeats the last observed 7-day cycle forward for as
many days as the horizon requires. It needs only one full cycle (7 observations) and no fitting
step, so it is always available whenever Holt-Winters is not. **It is not a weaker model by
definition** - see "When the baseline wins" below.

### Fallback hierarchy

Used in this order, and the response always says which one was actually used (`model_used`):

1. `holt_winters` - at least 21 days of history and a numerically sound fit.
2. `seasonal_naive` - a full 7-day cycle is available but Holt-Winters could not be used.
3. `historical_mean` - fewer than 7 days of history; the overall average is repeated.
4. `zero_demand` - every observed value is zero (checked before Holt-Winters is even attempted,
   since a constant-zero series has no variance to fit and would trivially forecast ~0 anyway).
5. `insufficient_history` - no sales history at all for the SKU.

A model-fitting error never crashes the server: it is caught and the hierarchy falls through to
the next model, with a warning explaining why.

### Chronological backtesting

The most recent 28 days are held out as a test set; both models are fit only on the data *before*
that window and evaluated on it (never on data the model has seen). After evaluation, the model
used for the actual future forecast is refit on the *entire* available history - the backtest
numbers describe past accuracy, not the exact parameters used going forward.

### Accuracy metrics

- **MAE** = mean absolute error, in the same units as the demand (units/day).
- **WAPE** = `sum(|actual - forecast|) / sum(actual) * 100`. Undefined (returned as `null`, not
  `NaN`) when the test window's actual demand sums to zero.
- **Forecast Bias** = `sum(forecast - actual) / sum(actual) * 100`. **Positive means
  over-forecasting, negative means under-forecasting.** Also `null` when actual demand sums to
  zero.

### When the baseline wins

On the demo SKU `DEMO-002` (weekly-seasonality profile, seed 42), the 28-day backtest gives:

| Model | MAE | WAPE | Bias |
|---|---|---|---|
| Holt-Winters | 2.66 | 17.80% | +5.55% |
| Seasonal Naive | 2.21 | 14.83% | +0.48% |

Seasonal Naive outperforms Holt-Winters on this SKU and test window. This is reported as-is
(`examples/sample_responses/forecast_demand.json`) - DemandPilot does not hide cases where the
simple baseline wins, and does not automatically swap in the better-scoring model for the actual
forecast (section 7.5 of `SPECIFICATION.md` explicitly does not require automatic model
selection).

### Prediction intervals

A 95% empirical prediction interval is produced only for `holt_winters` forecasts, via 500 Monte
Carlo simulations of the fitted model (`statsmodels`' `simulate(..., rng=...)`, seeded for
reproducibility), taking the 2.5th/97.5th percentiles at each horizon day and clipping to
non-negative. For every other model, the interval is `null` - it is not approximated as
"forecast ± 10%" or any other ad hoc rule, because that would not be statistically grounded.

## 2. Replenishment: the (R, S) periodic-review model

### Inventory Position

```text
inventory_position = on_hand + eligible_on_order - reserved
```

**Simplification**: with no delivery-date schedule in this MVP, *all* of `on_order` is treated as
`eligible_on_order` (available within the protection period). This is a documented approximation,
not real delivery scheduling.

### Protection Period

```text
protection_period = lead_time_days + review_period_days
```

The forecast used for replenishment must cover the *whole* protection period, not just the lead
time, because between review cycles no new order can be placed even if stock runs low.

### Safety Stock

```text
safety_stock = z_score * daily_demand_std * sqrt(protection_period)
```

`z_score` comes from `service_level` via the inverse standard normal CDF
(`statistics.NormalDist().inv_cdf`). `daily_demand_std` is preferably the standard deviation of
*backtest forecast errors* (if a reliable backtest was possible); otherwise it falls back to the
standard deviation of historical daily demand. This is an approximate cycle service level under
a normal-distribution assumption, independent daily deviations, and a fixed lead time - it is not
a guaranteed customer service level.

`safety_stock` is floored at 0. A `service_level` below 0.5 gives a negative z-score (the demo
data generator never produces one - its service levels are 0.90-0.98 - but the database schema
only enforces `0 < service_level < 1`, so a lower value is technically possible). A negative
safety stock would mean deliberately planning to stock *less* than the plain cumulative forecast,
which is not a meaningful "buffer" in this model, so the implementation clamps it to 0 instead of
returning a negative number.

### Target Stock Level

```text
target_level = cumulative_forecast(protection_period) + safety_stock
```

### Replenishment Quantity

```text
raw_order_qty = max(0, target_level - inventory_position)
order_qty = 0                                            if raw_order_qty == 0
order_qty = ceil(max(raw_order_qty, moq) / pack_size) * pack_size   otherwise
```

### Worked example (matches the unit test exactly)

Inputs: `service_level = 0.95`, `lead_time_days = 7`, `review_period_days = 7`,
`protection_period = 14`, `daily_demand_std = 10`, `cumulative forecast over 14 days = 200`,
`on_hand = 150`, `on_order = 0`, `reserved = 0`, `moq = 50`, `pack_size = 12`.

1. `z_score = NormalDist().inv_cdf(0.95) = 1.6448536269514715`
2. `safety_stock = 1.6448536269514715 * 10 * sqrt(14) = 61.544787234448826`
3. `target_level = 200 + 61.544787234448826 = 261.544787234448826`
4. `inventory_position = 150 + 0 - 0 = 150`
5. `raw_order_qty = max(0, 261.544787234448826 - 150) = 111.544787234448826`
6. `order_qty = ceil(max(111.544787234448826, 50) / 12) * 12 = ceil(9.2954...) * 12 = 10 * 12 = 120`

**Result: order 120 units.** This is exactly what
`recommend_replenishment(product, inventory, 200, 10, "holt_winters")` returns.

### Stockout Risk (rule-based, not a probability)

Risk is computed from the physically available stock after reservations
(`available = on_hand - reserved`) against the forecast, walking day by day to find the first day
the cumulative forecast would exceed `available`:

| Condition | Risk level |
|---|---|
| No forecast could be produced | cannot be assessed (flagged explicitly, not silently skipped) |
| `available <= 0` and forecasted demand > 0 | `HIGH` (already out of available stock) |
| Projected stockout day <= `lead_time_days` | `HIGH` (a reorder today could not arrive in time) |
| Projected stockout day <= `protection_period` | `MEDIUM` |
| Projected stockout day > `protection_period` | `LOW` |
| No projected stockout within the horizon | `NONE` |

`on_order` is reported as context only and never reduces the computed risk: without delivery-date
scheduling, assuming it arrives before the stockout would not be conservative.

## 3. MOQ and Pack Size

MOQ (minimum order quantity) and pack size are applied together, in that order: the raw
recommendation is first raised to at least the MOQ, then rounded *up* to the next whole multiple
of the pack size - even when the MOQ is not itself a multiple of the pack size (e.g. MOQ 50, pack
size 12 rounds up to 60, not 50).

## 4. Documented limitations

- Lead time is fixed/deterministic; no supply-side uncertainty is modeled.
- No delivery-date scheduling: all `on_order` is assumed available within the protection period.
- No lost-demand estimation for historical stockouts: the observed `quantity_sold` on a flagged
  stockout day is used as-is, with a warning that it may understate true demand.
- Backtesting uses a single fixed 28-day holdout window; it is a sanity check, not a rigorous
  cross-validated accuracy guarantee.
- Prediction intervals are only available for the Holt-Winters model and describe simulated model
  uncertainty, not a validated, out-of-sample coverage guarantee.
- The synthetic dataset's demand profiles are illustrative, not drawn from any real company's
  sales data.
- No ERP integration of any kind; this is a decision-support demo, not an operational system.
