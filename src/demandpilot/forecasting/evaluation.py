"""Chronological backtesting and forecast-accuracy metrics.

The test window is always the most recent `test_days` observations; the
model is fit only on the preceding (older) observations, so no future data
leaks into training (SPECIFICATION.md section 7.4). After evaluation, the
model used for the actual future forecast is refit on the full history
(handled by the caller, not here).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from demandpilot.forecasting.models import (
    MIN_HOLT_WINTERS_DAYS,
    MIN_SEASONAL_NAIVE_DAYS,
    _seasonal_naive_forecast,
    _try_fit_holt_winters,
)

DEFAULT_TEST_DAYS = 28


def mae(actual: list[float], forecast: list[float]) -> float:
    n = len(actual)
    return sum(abs(a - f) for a, f in zip(actual, forecast, strict=True)) / n


def wape(actual: list[float], forecast: list[float]) -> float | None:
    total_actual = sum(actual)
    if total_actual == 0:
        return None
    total_abs_error = sum(abs(a - f) for a, f in zip(actual, forecast, strict=True))
    return total_abs_error / total_actual * 100


def forecast_bias(actual: list[float], forecast: list[float]) -> float | None:
    """Positive: over-forecasting. Negative: under-forecasting."""
    total_actual = sum(actual)
    if total_actual == 0:
        return None
    total_error = sum(f - a for a, f in zip(actual, forecast, strict=True))
    return total_error / total_actual * 100


def _metrics(actual: list[float], forecast: list[float]) -> dict:
    errors = [a - f for a, f in zip(actual, forecast, strict=True)]
    return {
        "mae": mae(actual, forecast),
        "wape": wape(actual, forecast),
        "forecast_bias": forecast_bias(actual, forecast),
        # std of forecast errors on the held-out window; preferred safety-stock
        # input over historical demand std when backtesting succeeded (section 6.3).
        "residual_std": statistics.pstdev(errors) if len(errors) > 1 else 0.0,
    }


@dataclass
class BacktestResult:
    can_evaluate: bool
    test_days: int
    holt_winters: dict | None = None
    seasonal_naive: dict | None = None
    warning: str | None = None


def run_backtest(series: list[float], test_days: int = DEFAULT_TEST_DAYS) -> BacktestResult:
    if len(series) < test_days + MIN_SEASONAL_NAIVE_DAYS:
        return BacktestResult(
            can_evaluate=False,
            test_days=test_days,
            warning=(
                f"History ({len(series)} days) is too short for a reliable "
                f"{test_days}-day backtest; no accuracy metrics are available."
            ),
        )

    train, test = series[:-test_days], series[-test_days:]

    # train always has >= MIN_SEASONAL_NAIVE_DAYS observations here: the guard above
    # requires len(series) >= test_days + MIN_SEASONAL_NAIVE_DAYS.
    sn_forecast = _seasonal_naive_forecast(train, test_days)
    seasonal_naive_metrics = _metrics(test, sn_forecast)

    # An all-zero training window has no variance for Holt-Winters to fit: statsmodels'
    # AIC/BIC computation divides by SSE and raises RuntimeWarning('divide by zero in
    # log') on such degenerate data, and the resulting "fit" is meaningless (not a real
    # forecast skill measurement). generate_point_forecast() already treats an all-zero
    # series as the zero_demand fallback without ever attempting Holt-Winters; skipping
    # the attempt here too keeps the backtest consistent with the production model
    # hierarchy instead of reporting a spurious "perfect" Holt-Winters score for a model
    # that was never actually used for that SKU.
    train_is_all_zero = not any(v != 0 for v in train)
    holt_winters_metrics = None
    warning = None
    if len(train) >= MIN_HOLT_WINTERS_DAYS and not train_is_all_zero:
        fit = _try_fit_holt_winters(train)
        if fit is not None:
            hw_forecast = [max(0.0, v) for v in fit.forecast(test_days)]
            holt_winters_metrics = _metrics(test, hw_forecast)
    elif len(train) >= MIN_HOLT_WINTERS_DAYS and train_is_all_zero:
        warning = (
            "All observed demand in the training window is zero; Holt-Winters was not "
            "evaluated on it (the production forecast uses the zero_demand fallback "
            "instead, see SPECIFICATION.md section 7.3)."
        )

    return BacktestResult(
        can_evaluate=True,
        test_days=test_days,
        holt_winters=holt_winters_metrics,
        seasonal_naive=seasonal_naive_metrics,
        warning=warning,
    )
