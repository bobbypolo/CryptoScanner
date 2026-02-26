"""Tests for math_engine.py — Beta, Correlation, Trend Score, and Amihud.

All test cases verify the exact mathematical formulas and edge case guards
specified in the QUANT-004 acceptance criteria and quant-math/SPEC.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_scanner.math_engine import (
    calculate_amihud,
    calculate_beta,
    calculate_correlation,
    calculate_trend_score,
    compute_all_metrics,
)


# ---------------------------------------------------------------------------
# Fixtures: deterministic BTC returns for Beta / Correlation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def btc_returns_60d() -> pd.Series:
    """60 days of deterministic BTC returns using seed(42)."""
    np.random.seed(42)
    return pd.Series(np.random.randn(60) * 0.02)  # ~2% daily vol


# ---------------------------------------------------------------------------
# Beta tests
# ---------------------------------------------------------------------------


class TestBeta:
    """Verify rolling Beta calculation."""

    def test_asset_2x_btc_beta_equals_2(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly 2 * BTC returns -> Beta == 2.0."""
        asset_returns = 2 * btc_returns_60d
        beta = calculate_beta(asset_returns, btc_returns_60d)
        last_beta = beta.dropna().iloc[-1]
        assert np.isclose(last_beta, 2.0, atol=1e-10)

    def test_asset_neg1x_btc_beta_equals_neg1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly -1 * BTC returns -> Beta == -1.0."""
        asset_returns = -1 * btc_returns_60d
        beta = calculate_beta(asset_returns, btc_returns_60d)
        last_beta = beta.dropna().iloc[-1]
        assert np.isclose(last_beta, -1.0, atol=1e-10)

    def test_flat_btc_returns_nan(self) -> None:
        """BTC returns all zeros (zero variance) -> Beta is NaN, not inf."""
        btc_returns = pd.Series(np.zeros(60))
        asset_returns = pd.Series(np.random.randn(60) * 0.02)
        beta = calculate_beta(asset_returns, btc_returns)
        # Every value should be NaN because var is always 0
        assert beta.dropna().empty or pd.isna(beta.dropna().iloc[-1])
        # Specifically: no inf values allowed
        assert not np.any(np.isinf(beta.values))

    def test_insufficient_data_all_nan(self) -> None:
        """Only 15 data points, window=30, min_periods=20 -> all NaN."""
        btc_returns = pd.Series(np.random.randn(15) * 0.02)
        asset_returns = pd.Series(np.random.randn(15) * 0.03)
        beta = calculate_beta(asset_returns, btc_returns, window=30, min_periods=20)
        assert beta.notna().sum() == 0, "Expected all NaN with insufficient data"


# ---------------------------------------------------------------------------
# Correlation tests
# ---------------------------------------------------------------------------


class TestCorrelation:
    """Verify rolling Correlation calculation."""

    def test_asset_2x_btc_corr_equals_1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly 2 * BTC returns -> Correlation == 1.0."""
        asset_returns = 2 * btc_returns_60d
        corr = calculate_correlation(asset_returns, btc_returns_60d)
        last_corr = corr.dropna().iloc[-1]
        assert np.isclose(last_corr, 1.0, atol=1e-10)

    def test_asset_neg1x_btc_corr_equals_neg1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly -1 * BTC returns -> Correlation == -1.0."""
        asset_returns = -1 * btc_returns_60d
        corr = calculate_correlation(asset_returns, btc_returns_60d)
        last_corr = corr.dropna().iloc[-1]
        assert np.isclose(last_corr, -1.0, atol=1e-10)

    def test_insufficient_data_all_nan(self) -> None:
        """Only 15 data points, window=30, min_periods=20 -> all NaN."""
        btc_returns = pd.Series(np.random.randn(15) * 0.02)
        asset_returns = pd.Series(np.random.randn(15) * 0.03)
        corr = calculate_correlation(asset_returns, btc_returns, window=30, min_periods=20)
        assert corr.notna().sum() == 0, "Expected all NaN with insufficient data"


# ---------------------------------------------------------------------------
# Trend Score tests
# ---------------------------------------------------------------------------


class TestTrendScore:
    """Verify Trend Score with Z-score dampener."""

    def test_60pct_win_rate_avg_ratio_1_5(self) -> None:
        """60% win rate, avg_win/avg_loss=1.5 -> 0 < score <= 0.25."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        score = calculate_trend_score(returns)
        assert score > 0, f"Expected score > 0, got {score}"
        assert score <= 0.25, f"Expected score <= 0.25, got {score}"

    def test_30pct_win_rate_avg_ratio_0_8(self) -> None:
        """30% win rate, avg_win/avg_loss=0.8 -> score == 0.0 (no edge)."""
        returns = np.array([0.016] * 18 + [-0.02] * 42)
        score = calculate_trend_score(returns)
        assert score == 0.0, f"Expected score == 0.0, got {score}"

    def test_90pct_win_rate_capped_at_max(self) -> None:
        """90% win rate -> score <= max_fraction (0.25 cap enforced)."""
        returns = np.array([0.01] * 54 + [-0.005] * 6)
        score = calculate_trend_score(returns)
        assert score <= 0.25, f"Expected score <= 0.25, got {score}"
        assert score > 0, f"Expected score > 0, got {score}"

    def test_all_positive_returns_zero(self) -> None:
        """ALL positive returns (no losses) -> score == 0.0."""
        returns = np.array([0.01] * 60)
        score = calculate_trend_score(returns)
        assert score == 0.0, f"Expected score == 0.0 with no losses, got {score}"

    def test_all_negative_returns_zero(self) -> None:
        """ALL negative returns (no wins) -> score == 0.0."""
        returns = np.array([-0.01] * 60)
        score = calculate_trend_score(returns)
        assert score == 0.0, f"Expected score == 0.0 with no wins, got {score}"

    def test_insufficient_trades(self) -> None:
        """Fewer than min_trades -> score == 0.0."""
        returns = np.array([0.01] * 10 + [-0.01] * 5)
        score = calculate_trend_score(returns, min_trades=30)
        assert score == 0.0, f"Expected score == 0.0 with insufficient trades"

    def test_zscore_dampener_applied(self) -> None:
        """Parabolic close prices (Z > 2.5) with positive edge -> score halved."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        # Build close prices with a massive spike at the end:
        # 59 flat values at 10.0, then last value at 100.0
        # This gives Z ≈ 5.3 (well above 2.5 threshold)
        close = pd.Series(np.append(np.full(59, 10.0), [100.0]))
        score_no_close = calculate_trend_score(returns)
        score_with_close = calculate_trend_score(returns, close_prices=close)
        assert score_no_close > 0
        assert score_with_close < score_no_close
        assert np.isclose(score_with_close, score_no_close * 0.5, rtol=0.01)

    def test_zscore_below_threshold(self) -> None:
        """Close prices with Z ~ 1.5 -> score unchanged."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        # Gently rising close prices — Z should be below 2.5
        close = pd.Series(np.linspace(10.0, 12.0, 60))
        score_no_close = calculate_trend_score(returns)
        score_with_close = calculate_trend_score(returns, close_prices=close)
        assert score_with_close == score_no_close

    def test_zscore_no_close_prices(self) -> None:
        """close_prices=None -> score unchanged."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        score = calculate_trend_score(returns, close_prices=None)
        assert score > 0

    def test_zscore_flat_std(self) -> None:
        """Constant close prices (std=0) -> score unchanged (no dampening)."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        close = pd.Series(np.full(60, 10.0))
        score_no_close = calculate_trend_score(returns)
        score_with_close = calculate_trend_score(returns, close_prices=close)
        assert score_with_close == score_no_close

    def test_zscore_insufficient_data(self) -> None:
        """Only 20 close prices -> skip Z-score, score unchanged."""
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        close = pd.Series(np.linspace(10.0, 50.0, 20))  # less than 30
        score_no_close = calculate_trend_score(returns)
        score_with_close = calculate_trend_score(returns, close_prices=close)
        assert score_with_close == score_no_close


# ---------------------------------------------------------------------------
# Amihud tests
# ---------------------------------------------------------------------------


class TestAmihud:
    """Verify Amihud illiquidity ratio calculation."""

    def test_basic_calc(self) -> None:
        """Basic Amihud: mean(|return| / dollar_volume)."""
        np.random.seed(42)
        close = pd.Series(np.linspace(10, 12, 60))
        volume = pd.Series(np.full(60, 1_000_000.0))
        returns = close.pct_change()
        result = calculate_amihud(returns, volume, close)
        assert isinstance(result, float)
        assert result > 0
        assert not np.isnan(result)

    def test_zero_volume_nan(self) -> None:
        """Zero-volume candles produce NaN (not inf)."""
        close = pd.Series(np.linspace(10, 12, 60))
        volume = pd.Series(np.zeros(60))  # all zero volume
        returns = close.pct_change()
        result = calculate_amihud(returns, volume, close)
        assert np.isnan(result)

    def test_insufficient_data_nan(self) -> None:
        """Fewer than min_periods observations returns NaN."""
        close = pd.Series([10.0, 11.0, 12.0])
        volume = pd.Series([1e6, 1e6, 1e6])
        returns = close.pct_change()
        result = calculate_amihud(returns, volume, close, window=30, min_periods=20)
        assert np.isnan(result)

    def test_zero_returns_zero(self) -> None:
        """Constant close prices (zero returns) produce 0."""
        close = pd.Series(np.full(60, 10.0))
        volume = pd.Series(np.full(60, 1_000_000.0))
        returns = close.pct_change()
        result = calculate_amihud(returns, volume, close)
        assert result == 0.0


# ---------------------------------------------------------------------------
# compute_all_metrics tests
# ---------------------------------------------------------------------------


class TestComputeAllMetrics:
    """Verify the master orchestration function."""

    def test_compute_all_metrics_basic(self) -> None:
        """Basic end-to-end: BTC + one altcoin with 60 close prices."""
        np.random.seed(42)
        # Generate 60 BTC close prices
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)
        # Altcoin that amplifies BTC moves: correlated price series
        alt_close = 50 + np.cumsum(np.random.randn(60) * 3)
        alt_volume = np.full(60, 1_000_000.0)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT/USDT": pd.DataFrame({"close": alt_close, "volume": alt_volume}),
        }

        result = compute_all_metrics(ohlcv_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "ALT/USDT"

        # Verify all expected columns
        for col in ["symbol", "beta", "correlation", "trend_score", "amihud", "data_days"]:
            assert col in result.columns, f"Missing column: {col}"

        # Amihud should be a valid number
        assert not np.isnan(result.iloc[0]["amihud"])

        # data_days should be count of non-NaN returns (59 max from 60 closes)
        assert result.iloc[0]["data_days"] == 59

    def test_compute_all_metrics_data_days_count(self) -> None:
        """data_days = count of non-NaN values in RETURNS series, not close."""
        btc_close = pd.Series(range(1, 61), dtype=float)
        alt_close = pd.Series(range(1, 61), dtype=float)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT/USDT": pd.DataFrame({"close": alt_close}),
        }

        result = compute_all_metrics(ohlcv_data)
        # 60 closes -> pct_change -> first is NaN -> 59 non-NaN returns
        assert result.iloc[0]["data_days"] == 59

    def test_compute_all_metrics_excludes_btc(self) -> None:
        """BTC/USDT itself should not appear in the results."""
        np.random.seed(42)
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
        }

        result = compute_all_metrics(ohlcv_data)
        assert len(result) == 0

    def test_compute_all_metrics_multiple_altcoins(self) -> None:
        """Multiple altcoins are all processed."""
        np.random.seed(42)
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT1/USDT": pd.DataFrame({"close": 50 + np.cumsum(np.random.randn(60))}),
            "ALT2/USDT": pd.DataFrame({"close": 30 + np.cumsum(np.random.randn(60))}),
        }

        result = compute_all_metrics(ohlcv_data)
        assert len(result) == 2
        symbols = set(result["symbol"].tolist())
        assert symbols == {"ALT1/USDT", "ALT2/USDT"}
