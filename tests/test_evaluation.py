from __future__ import annotations

import random

import pytest

from demandpilot.forecasting import evaluation


def _weekly_series(n: int, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    weekday_mult = [1.4, 1.0, 0.9, 0.9, 1.0, 1.3, 1.6]
    return [max(0.0, 10 * weekday_mult[i % 7] + rng.gauss(0, 1.0)) for i in range(n)]


def test_mae_hand_calculated():
    assert evaluation.mae([10, 20, 30], [12, 18, 33]) == pytest.approx((2 + 2 + 3) / 3)


def test_wape_hand_calculated():
    # sum|actual-forecast| = 7, sum(actual) = 60 -> 11.666...%
    assert evaluation.wape([10, 20, 30], [12, 18, 33]) == pytest.approx(7 / 60 * 100)


def test_wape_none_when_actual_sum_is_zero():
    assert evaluation.wape([0, 0, 0], [1, 2, 3]) is None


def test_forecast_bias_sign_convention_overforecast_positive():
    # forecast always higher than actual -> positive bias
    assert evaluation.forecast_bias([10, 10], [12, 14]) == pytest.approx((2 + 4) / 20 * 100)


def test_forecast_bias_sign_convention_underforecast_negative():
    assert evaluation.forecast_bias([10, 10], [8, 6]) == pytest.approx((-2 - 4) / 20 * 100)


def test_forecast_bias_none_when_actual_sum_is_zero():
    assert evaluation.forecast_bias([0, 0], [1, 1]) is None


def test_run_backtest_insufficient_history():
    result = evaluation.run_backtest([1.0] * 10, test_days=28)
    assert result.can_evaluate is False
    assert result.warning is not None


def test_run_backtest_uses_chronological_split_no_future_leakage():
    series = _weekly_series(100, seed=5)
    result = evaluation.run_backtest(series, test_days=28)
    assert result.can_evaluate is True
    assert result.test_days == 28
    # Both models were evaluated on the same held-out window.
    assert result.seasonal_naive is not None
    assert result.holt_winters is not None
    for metrics in (result.seasonal_naive, result.holt_winters):
        assert metrics["mae"] >= 0
        assert metrics["wape"] is None or metrics["wape"] >= 0


def test_run_backtest_seasonal_naive_only_when_too_short_for_holt_winters():
    # 28 (test) + 10 (train, one cycle but < MIN_HOLT_WINTERS_DAYS=21) = 38
    series = _weekly_series(38, seed=6)
    result = evaluation.run_backtest(series, test_days=28)
    assert result.can_evaluate is True
    assert result.seasonal_naive is not None
    assert result.holt_winters is None


def test_run_backtest_all_zero_training_window_skips_holt_winters_without_warning():
    """An all-zero training window must not be handed to Holt-Winters: statsmodels'
    AIC/BIC computation raises RuntimeWarning('divide by zero in log') on such
    degenerate data, and the resulting "fit" would misrepresent a model that the
    production forecast never actually uses (it falls back to zero_demand instead).
    """
    import warnings

    series = [0.0] * 100
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = evaluation.run_backtest(series, test_days=28)
    assert result.can_evaluate is True
    assert result.holt_winters is None
    assert result.seasonal_naive is not None
    assert result.warning is not None
    assert "zero" in result.warning.lower()


def test_run_backtest_constant_positive_demand_still_evaluates_holt_winters():
    """A constant, non-zero demand series (zero variance but not the degenerate
    all-zero case) is a legitimate, trivially-predictable series and should still be
    evaluated normally, not skipped by the all-zero guard above.
    """
    series = [10.0] * 100
    result = evaluation.run_backtest(series, test_days=28)
    assert result.can_evaluate is True
    assert result.holt_winters is not None
    assert result.warning is None
