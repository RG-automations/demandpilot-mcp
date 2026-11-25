from __future__ import annotations

import math
import random

import pytest

from demandpilot.forecasting import models


def _weekly_series(n: int, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    weekday_mult = [1.4, 1.0, 0.9, 0.9, 1.0, 1.3, 1.6]
    return [max(0.0, 10 * weekday_mult[i % 7] + rng.gauss(0, 1.0)) for i in range(n)]


def test_generate_point_forecast_rejects_zero_or_negative_horizon():
    # statsmodels' Holt-Winters fit.forecast(0) raises ValueError internally; this
    # function must validate at its own boundary instead of leaking that error.
    with pytest.raises(ValueError):
        models.generate_point_forecast([5.0] * 40, horizon_days=0)
    with pytest.raises(ValueError):
        models.generate_point_forecast([5.0] * 40, horizon_days=-1)


def test_try_fit_holt_winters_returns_none_on_fitting_exception():
    # Fewer points than seasonal_periods makes statsmodels raise during construction/fit.
    assert models._try_fit_holt_winters([1.0, 2.0, 3.0]) is None


def test_try_fit_holt_winters_returns_none_on_non_finite_fitted_values(monkeypatch):
    class FakeFit:
        fittedvalues = [1.0, float("nan"), 3.0]

    class FakeModel:
        def fit(self):
            return FakeFit()

    monkeypatch.setattr(models, "ExponentialSmoothing", lambda *a, **k: FakeModel())
    series = _weekly_series(30, seed=9)
    assert models._try_fit_holt_winters(series) is None


def test_insufficient_history_returns_empty_forecast():
    result = models.generate_point_forecast([], horizon_days=14)
    assert result.model_used == models.MODEL_INSUFFICIENT_HISTORY
    assert result.daily_forecast == []
    assert result.warnings


def test_zero_demand_series_returns_zero_forecast():
    result = models.generate_point_forecast([0.0] * 40, horizon_days=14)
    assert result.model_used == models.MODEL_ZERO_DEMAND
    assert result.daily_forecast == [0.0] * 14


def test_very_short_history_uses_historical_mean():
    result = models.generate_point_forecast([5.0, 6.0, 7.0], horizon_days=5)
    assert result.model_used == models.MODEL_HISTORICAL_MEAN
    assert result.daily_forecast == [6.0] * 5


def test_one_full_cycle_but_below_hw_minimum_uses_seasonal_naive():
    series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]  # 10 days, 1 cycle
    result = models.generate_point_forecast(series, horizon_days=9)
    assert result.model_used == models.MODEL_SEASONAL_NAIVE
    last_cycle = series[-7:]
    assert result.daily_forecast == [last_cycle[i % 7] for i in range(9)]


def test_seasonal_naive_tiles_last_cycle_beyond_one_period():
    series = [float(i % 7) for i in range(14)]
    result = models.generate_point_forecast(series[:10], horizon_days=16)
    assert len(result.daily_forecast) == 16


def test_sufficient_seasonal_history_uses_holt_winters():
    series = _weekly_series(60, seed=1)
    result = models.generate_point_forecast(series, horizon_days=14)
    assert result.model_used == models.MODEL_HOLT_WINTERS
    assert len(result.daily_forecast) == 14
    assert all(v >= 0 for v in result.daily_forecast)


def test_forecast_values_are_never_negative_for_declining_trend():
    series = [max(0.0, 20 - 0.5 * i) for i in range(40)]
    result = models.generate_point_forecast(series, horizon_days=30)
    assert all(v >= 0 for v in result.daily_forecast)


def test_holt_winters_fit_failure_falls_back_to_seasonal_naive(monkeypatch):
    monkeypatch.setattr(models, "_try_fit_holt_winters", lambda series: None)
    series = _weekly_series(60, seed=2)
    result = models.generate_point_forecast(series, horizon_days=10)
    assert result.model_used == models.MODEL_SEASONAL_NAIVE
    assert any("holt-winters" in w.lower() for w in result.warnings)


def test_prediction_interval_none_for_non_holt_winters_model():
    result = models.generate_point_forecast([5.0, 6.0, 7.0], horizon_days=5)
    assert models.prediction_interval(result, 5, seed=42) is None


def test_prediction_interval_bounds_and_determinism():
    series = _weekly_series(60, seed=3)
    result = models.generate_point_forecast(series, horizon_days=14)
    assert result.model_used == models.MODEL_HOLT_WINTERS

    interval_a = models.prediction_interval(result, 14, seed=42)
    interval_b = models.prediction_interval(result, 14, seed=42)
    assert interval_a is not None
    lower_a, upper_a = interval_a
    lower_b, upper_b = interval_b

    assert lower_a == lower_b
    assert upper_a == upper_b
    assert all(lo >= 0 for lo in lower_a)
    assert all(up >= lo for lo, up in zip(lower_a, upper_a, strict=True))
    assert all(math.isfinite(v) for v in lower_a + upper_a)


def test_prediction_interval_differs_with_different_seed():
    series = _weekly_series(60, seed=4)
    result = models.generate_point_forecast(series, horizon_days=14)
    interval_a = models.prediction_interval(result, 14, seed=1)
    interval_b = models.prediction_interval(result, 14, seed=2)
    assert interval_a != interval_b
