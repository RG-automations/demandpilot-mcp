"""Demand forecasting: Holt-Winters, Seasonal Naive, and a documented fallback
hierarchy. All randomness (Monte Carlo prediction intervals) is seeded for
reproducibility.

Fallback hierarchy (SPECIFICATION.md section 7.3), in the order applied:
    1. holt_winters      - enough history (>= MIN_HOLT_WINTERS_DAYS) and the
                            model fits without producing NaN/inf values.
    2. seasonal_naive     - a full 7-day cycle is available but Holt-Winters
                            could not be used.
    3. historical_mean    - history shorter than one full seasonal cycle.
    4. zero_demand        - history exists but every observed value is zero.
    5. insufficient_history - no observations at all.

Implementation note: an all-zero series is detected before attempting
Holt-Winters, because a constant-zero series has no variance for the model to
fit and the resulting forecast would be ~0 regardless; this is a direct,
equivalent shortcut to letting Holt-Winters fail and falling through to the
zero_demand case, documented here per SPECIFICATION.md section 0 (deviations
must be explained, not hidden).

Missing calendar days (no sales_history row) are never treated as zero
demand (section 5.4): the input series is the sequence of *observed*
quantities only, and callers must report how many days were missing as a
warning - this module does not see calendar dates at all.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

SEASONAL_PERIODS = 7
MIN_HOLT_WINTERS_DAYS = 3 * SEASONAL_PERIODS  # 3 full cycles: avoids overfitting on thin data
MIN_SEASONAL_NAIVE_DAYS = SEASONAL_PERIODS
N_SIMULATIONS = 500

MODEL_HOLT_WINTERS = "holt_winters"
MODEL_SEASONAL_NAIVE = "seasonal_naive"
MODEL_HISTORICAL_MEAN = "historical_mean"
MODEL_ZERO_DEMAND = "zero_demand"
MODEL_INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass
class PointForecast:
    model_used: str
    daily_forecast: list[float]
    warnings: list[str] = field(default_factory=list)
    _fit: object | None = None  # internal: fitted statsmodels result, for simulate()


def _seasonal_naive_forecast(series: list[float], horizon_days: int) -> list[float]:
    last_cycle = series[-SEASONAL_PERIODS:]
    return [last_cycle[i % SEASONAL_PERIODS] for i in range(horizon_days)]


def _historical_mean_forecast(series: list[float], horizon_days: int) -> list[float]:
    mean = sum(series) / len(series)
    return [mean] * horizon_days


def _try_fit_holt_winters(series: list[float]):
    """Returns a fitted statsmodels result, or None if fitting is unreliable."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                np.asarray(series, dtype=float),
                trend=None,
                seasonal="add",
                seasonal_periods=SEASONAL_PERIODS,
                initialization_method="estimated",
            )
            fit = model.fit()
    except Exception:
        return None
    fitted_values = np.asarray(fit.fittedvalues)
    if not np.all(np.isfinite(fitted_values)):
        return None
    return fit


def generate_point_forecast(series: list[float], horizon_days: int) -> PointForecast:
    """Picks the first usable model in the fallback hierarchy and returns a
    non-negative daily forecast of length `horizon_days`.
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be >= 1, got {horizon_days}")

    if len(series) == 0:
        return PointForecast(
            MODEL_INSUFFICIENT_HISTORY,
            [],
            warnings=["No sales history is available for this SKU; forecasting is not possible."],
        )

    if all(v == 0 for v in series):
        return PointForecast(
            MODEL_ZERO_DEMAND,
            [0.0] * horizon_days,
            warnings=["All observed demand in the available history is zero."],
        )

    if len(series) >= MIN_HOLT_WINTERS_DAYS:
        fit = _try_fit_holt_winters(series)
        if fit is not None:
            forecast = np.clip(np.asarray(fit.forecast(horizon_days)), 0, None).tolist()
            return PointForecast(MODEL_HOLT_WINTERS, forecast, _fit=fit)
        if len(series) >= MIN_SEASONAL_NAIVE_DAYS:
            return PointForecast(
                MODEL_SEASONAL_NAIVE,
                _seasonal_naive_forecast(series, horizon_days),
                warnings=[
                    "Holt-Winters could not be reliably fitted; used Seasonal Naive instead."
                ],
            )

    if len(series) >= MIN_SEASONAL_NAIVE_DAYS:
        return PointForecast(MODEL_SEASONAL_NAIVE, _seasonal_naive_forecast(series, horizon_days))

    return PointForecast(
        MODEL_HISTORICAL_MEAN,
        _historical_mean_forecast(series, horizon_days),
        warnings=[
            f"History ({len(series)} observation(s)) is shorter than one full "
            f"{SEASONAL_PERIODS}-day seasonal cycle; used the historical mean instead."
        ],
    )


def prediction_interval(
    forecast: PointForecast, horizon_days: int, seed: int
) -> tuple[list[float], list[float]] | None:
    """95% empirical prediction interval from Monte Carlo simulation of the
    fitted Holt-Winters model. Returns None if the model used does not
    support a statistically grounded interval (section 7.6).
    """
    if forecast.model_used != MODEL_HOLT_WINTERS or forecast._fit is None:
        return None
    sims = forecast._fit.simulate(
        nsimulations=horizon_days, repetitions=N_SIMULATIONS, rng=np.random.default_rng(seed)
    )
    sims = np.clip(np.asarray(sims), 0, None)
    lower = np.percentile(sims, 2.5, axis=1)
    upper = np.percentile(sims, 97.5, axis=1)
    upper = np.maximum(upper, lower)
    if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
        return None
    return lower.tolist(), upper.tolist()
